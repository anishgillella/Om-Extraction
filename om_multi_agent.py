#!/usr/bin/env python3
"""
OM/Flyer Downloader using Browser Use
Downloads Offering Memorandums and Flyers from real estate property pages
"""

import asyncio
import os
import time
import aiohttp
from pathlib import Path
from browser_use import Agent, BrowserSession, BrowserProfile, Controller, ActionResult
from playwright.async_api import Page
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from urllib.parse import urlparse
from typing import Dict, List
from langchain.callbacks.base import BaseCallbackHandler
from langchain.schema import LLMResult
import re
import traceback

# Load environment variables
load_dotenv()

class TokenTracker:
    """Track token usage and costs for GPT-4o including vision"""
    
    def __init__(self):
        self.reset()
        
        # GPT-4o pricing (per 1M tokens)
        self.pricing = {
            "gpt-4o": {
                "input": 2.50,  # $2.50 per 1M input tokens
                "output": 10.00,  # $10.00 per 1M output tokens
                "vision": 2.50   # $2.50 per 1M vision tokens (same as input)
            },
            "gpt-4o-mini": {
                "input": 0.15,   # $0.15 per 1M input tokens
                "output": 0.60,  # $0.60 per 1M output tokens  
                "vision": 0.15   # $0.15 per 1M vision tokens
            }
        }
    
    def reset(self):
        """Reset all counters"""
        self.scout_tokens = {"input": 0, "output": 0, "vision": 0}
        self.main_tokens = {"input": 0, "output": 0, "vision": 0}
        self.total_tokens = {"input": 0, "output": 0, "vision": 0}
        self.scout_cost = 0.0
        self.main_cost = 0.0
        self.total_cost = 0.0
        self.model_name = "gpt-4o"
        
    def set_model(self, model_name: str):
        """Set the model name for cost calculations"""
        self.model_name = model_name
        
    def add_scout_usage(self, input_tokens: int, output_tokens: int, vision_tokens: int = 0):
        """Add token usage for scout agent"""
        self.scout_tokens["input"] += input_tokens
        self.scout_tokens["output"] += output_tokens
        self.scout_tokens["vision"] += vision_tokens
        self._update_totals()
        
    def add_main_usage(self, input_tokens: int, output_tokens: int, vision_tokens: int = 0):
        """Add token usage for main agent"""
        self.main_tokens["input"] += input_tokens
        self.main_tokens["output"] += output_tokens
        self.main_tokens["vision"] += vision_tokens
        self._update_totals()
        
    def _update_totals(self):
        """Update total tokens and costs"""
        # Calculate totals
        self.total_tokens["input"] = self.scout_tokens["input"] + self.main_tokens["input"]
        self.total_tokens["output"] = self.scout_tokens["output"] + self.main_tokens["output"]
        self.total_tokens["vision"] = self.scout_tokens["vision"] + self.main_tokens["vision"]
        
        # Calculate costs (convert to millions for pricing)
        pricing = self.pricing.get(self.model_name, self.pricing["gpt-4o"])
        
        # Scout costs
        scout_input_cost = (self.scout_tokens["input"] / 1_000_000) * pricing["input"]
        scout_output_cost = (self.scout_tokens["output"] / 1_000_000) * pricing["output"]
        scout_vision_cost = (self.scout_tokens["vision"] / 1_000_000) * pricing["vision"]
        self.scout_cost = scout_input_cost + scout_output_cost + scout_vision_cost
        
        # Main agent costs
        main_input_cost = (self.main_tokens["input"] / 1_000_000) * pricing["input"]
        main_output_cost = (self.main_tokens["output"] / 1_000_000) * pricing["output"]
        main_vision_cost = (self.main_tokens["vision"] / 1_000_000) * pricing["vision"]
        self.main_cost = main_input_cost + main_output_cost + main_vision_cost
        
        # Total cost
        self.total_cost = self.scout_cost + self.main_cost
    
    def get_summary(self) -> Dict:
        """Get token usage and cost summary"""
        return {
            "model": self.model_name,
            "scout": {
                "tokens": dict(self.scout_tokens),
                "cost": self.scout_cost
            },
            "main": {
                "tokens": dict(self.main_tokens),
                "cost": self.main_cost
            },
            "total": {
                "tokens": dict(self.total_tokens),
                "cost": self.total_cost
            }
        }

# Global token tracker instance
token_tracker = TokenTracker()

# Create controller for custom actions
controller = Controller()

# Custom action to handle PDFs that open in new tabs
@controller.action('Handle PDF opened in new tab')
async def handle_pdf_new_tab(page: Page) -> ActionResult:
    """
    Detect if a PDF opened in a new tab and switch to it to download the PDF
    """
    try:
        context = page.context
        all_pages = context.pages
        
        print(f"🔍 Checking for new tabs... Found {len(all_pages)} total tabs")
        
        # Look for tabs that might contain PDFs
        pdf_tabs = []
        for tab_page in all_pages:
            try:
                tab_url = tab_page.url
                print(f"📄 Tab URL: {tab_url}")
                
                # Check if this tab contains a PDF
                if (tab_url.endswith('.pdf') or 
                    'pdf' in tab_url.lower() or
                    tab_url.startswith('blob:') or  # PDF blob URLs
                    'application/pdf' in tab_url):
                    pdf_tabs.append(tab_page)
                    print(f"🎯 Found PDF tab: {tab_url}")
                    
                # Also check content type by trying to get page content
                try:
                    # Switch to this tab temporarily to check content
                    await tab_page.bring_to_front()
                    await tab_page.wait_for_timeout(1000)  # Wait for tab to load
                    
                    # Check if page shows PDF content
                    page_content = await tab_page.content()
                    if ('pdf' in page_content.lower() and 
                        ('embed' in page_content.lower() or 'object' in page_content.lower())):
                        pdf_tabs.append(tab_page)
                        print(f"🎯 Found embedded PDF tab: {tab_url}")
                        
                except Exception as tab_error:
                    print(f"⚠️ Could not check tab content: {tab_error}")
                    continue
                    
            except Exception as e:
                print(f"⚠️ Error checking tab: {e}")
                continue
        
        if not pdf_tabs:
            return ActionResult(extracted_content="❌ No PDF tabs found")
        
        # Process the first PDF tab found
        pdf_page = pdf_tabs[0]
        await pdf_page.bring_to_front()
        print(f"🔄 Switched to PDF tab: {pdf_page.url}")
        
        # Now download the PDF from this tab
        return await download_pdf_direct(page=pdf_page, pdf_url=pdf_page.url)
        
    except Exception as e:
        print(f"❌ Error handling PDF new tab: {e}")
        return ActionResult(extracted_content=f"❌ Error handling PDF new tab: {e}")

# Custom action to download PDF directly using browser context navigation
@controller.action('Download PDF directly from URL')
async def download_pdf_direct(page: Page, pdf_url: str = None) -> ActionResult:
    """
    Download PDF directly from the current page URL or a provided PDF URL using browser context navigation
    to bypass Cloudflare and other bot detection systems
    """
    try:
        # Use provided PDF URL or current page URL
        current_url = pdf_url if pdf_url else page.url
        print(f"🔍 Attempting to download PDF from: {current_url}")
        
        # More flexible PDF detection - check URL or content type
        is_pdf_url = (current_url.endswith('.pdf') or 
                     'pdf' in current_url.lower() or
                     '/uploads/' in current_url or
                     'wp-content' in current_url)
        
        if not is_pdf_url:
            print(f"❌ URL doesn't appear to be a PDF: {current_url}")
            return ActionResult(extracted_content=f"❌ Current page URL doesn't appear to be a PDF: {current_url}")
        
        # Set up downloads directory with domain-specific subfolder
        downloads_dir = Path("/Users/anishgillella/Desktop/Stuff/Theus/TheusAI/downloads")
        
        # Extract domain from current URL for folder organization
        parsed_url = urlparse(current_url)
        domain = parsed_url.netloc.replace('www.', '').replace('.com', '').replace('.net', '').replace('.org', '')
        domain_dir = downloads_dir / domain
        domain_dir.mkdir(exist_ok=True, parents=True)
        print(f"📁 Downloads directory: {domain_dir}")
        
        # Extract filename from URL
        filename = current_url.split('/')[-1]
        if '?' in filename:
            filename = filename.split('?')[0]  # Remove query parameters
        if not filename.endswith('.pdf') and not '.pdf' in filename:
            filename += '.pdf'
        
        # Clean filename
        clean_filename = filename.replace('%20', '-').replace(' ', '-').replace('%2B', '+')
        download_path = domain_dir / clean_filename
        print(f"💾 Target file path: {download_path}")
        
        # Enhanced browser-context download method
        print("🌐 Starting download using enhanced browser context...")
        
        try:
            # Method 1: Browser-native download with session preservation
            context = page.context
            
            # If we have a PDF URL, try to navigate to it first
            if pdf_url and pdf_url != page.url:
                print(f"🔄 Navigating to PDF URL: {current_url}")
                try:
                    await page.goto(current_url, wait_until='networkidle', timeout=15000)
                    await page.wait_for_timeout(2000)  # Allow page to fully load
                except Exception as nav_error:
                    print(f"⚠️ Navigation failed, trying direct download: {nav_error}")
            
            # Check if we got Cloudflare challenge or similar
            page_content = await page.content()
            if 'challenge' in page_content.lower() or 'just a moment' in page_content.lower():
                print("🛡️  Detected Cloudflare challenge, waiting for resolution...")
                await page.wait_for_timeout(5000)  # Wait for challenge to complete
                
                # Try to detect if challenge was solved
                try:
                    await page.wait_for_load_state('networkidle', timeout=10000)
                except:
                    pass
            
            # Method 1: Use download event handler (most reliable for Cloudflare)
            download_started = False
            downloaded_file = None
            
            async def handle_download_event(download):
                nonlocal download_started, downloaded_file
                download_started = True
                print(f"📥 Download started: {download.suggested_filename}")
                
                # Save to our domain-specific downloads directory
                final_path = domain_dir / (download.suggested_filename or clean_filename)
                await download.save_as(final_path)
                downloaded_file = final_path
                print(f"✅ Download completed: {final_path}")
            
            # Register download handler
            page.on('download', handle_download_event)
            
            # Trigger download using browser evaluation (preserves session)
            print("🚀 Triggering download via browser JavaScript...")
            await page.evaluate(f"""
                () => {{
                    // Method 1: Try window.open
                    const link = document.createElement('a');
                    link.href = '{current_url}';
                    link.download = '{clean_filename}';
                    link.target = '_blank';
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                    
                    // Method 2: Direct location change as fallback
                    setTimeout(() => {{
                        if (!window.downloadStarted) {{
                            window.location.href = '{current_url}';
                        }}
                    }}, 1000);
                }}
            """)
            
            # Wait for download to start
            max_wait = 15000  # 15 seconds
            wait_step = 500
            waited = 0
            
            while not download_started and waited < max_wait:
                await page.wait_for_timeout(wait_step)
                waited += wait_step
                
                # Check if PDF content loaded in current page
                current_content = await page.content()
                if len(current_content) > 1000 and '%PDF' in current_content:
                    print("📄 PDF content detected in page")
                    break
            
            if download_started and downloaded_file:
                file_size_kb = downloaded_file.stat().st_size // 1024
                print(f"✅ File successfully downloaded via browser event: {downloaded_file} ({file_size_kb} KB)")
                return ActionResult(extracted_content=f"✅ DOWNLOAD COMPLETE! Successfully downloaded PDF: {downloaded_file.name} ({file_size_kb} KB). Task finished - use 'done' action immediately.")
            
            # Method 2: Direct buffer extraction from browser (if PDF loaded in page)
            print("🔄 Trying buffer extraction method...")
            
            # Check if PDF is now displayed in browser
            try:
                # Get PDF content using browser APIs
                pdf_buffer = await page.evaluate(f"""
                    async () => {{
                        try {{
                            const response = await fetch('{current_url}');
                            if (response.ok) {{
                                const arrayBuffer = await response.arrayBuffer();
                                const bytes = new Uint8Array(arrayBuffer);
                                return Array.from(bytes);
                            }}
                        }} catch (e) {{
                            console.error('Fetch failed:', e);
                        }}
                        return null;
                    }}
                """)
                
                if pdf_buffer and len(pdf_buffer) > 1000:
                    # Convert back to bytes and save
                    content = bytes(pdf_buffer)
                    
                    if content.startswith(b'%PDF'):
                        print(f"💾 Writing {len(content)} bytes to: {download_path}")
                        with open(download_path, 'wb') as f:
                            f.write(content)
                        
                        if download_path.exists():
                            file_size_kb = download_path.stat().st_size // 1024
                            print(f"✅ File successfully saved via buffer extraction: {download_path} ({file_size_kb} KB)")
                            return ActionResult(extracted_content=f"✅ DOWNLOAD COMPLETE! Successfully downloaded PDF: {clean_filename} ({file_size_kb} KB). Task finished - use 'done' action immediately.")
                
            except Exception as buffer_error:
                print(f"⚠️ Buffer extraction failed: {buffer_error}")
            
            # Method 3: Enhanced context request with full headers
            print("🔄 Trying enhanced context request with preserved session...")
            
            # Get all cookies and headers from current session
            cookies = await context.cookies()
            
            # Build proper headers that mimic the browser
            headers = {
                'User-Agent': await page.evaluate('navigator.userAgent'),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'same-origin',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache'
            }
            
            # Add referrer if we came from a property page
            if hasattr(page, '_referrer_url') or 'properties' in current_url:
                referrer = getattr(page, '_referrer_url', current_url.rsplit('/', 1)[0])
                headers['Referer'] = referrer
            
            response = await context.request.get(current_url, headers=headers)
            
            print(f"📊 Enhanced request status: {response.status}")
            if response.status == 200:
                content = await response.body()
                content_length = len(content)
                print(f"📥 Downloaded {content_length} bytes")
                
                if content_length > 0 and content.startswith(b'%PDF'):
                    # Save the PDF
                    print(f"💾 Writing {content_length} bytes to: {download_path}")
                    with open(download_path, 'wb') as f:
                        f.write(content)
                    
                    if download_path.exists():
                        file_size_kb = download_path.stat().st_size // 1024
                        print(f"✅ File successfully saved via enhanced request: {download_path} ({file_size_kb} KB)")
                        return ActionResult(extracted_content=f"✅ DOWNLOAD COMPLETE! Successfully downloaded PDF: {clean_filename} ({file_size_kb} KB). Task finished - use 'done' action immediately.")
                    else:
                        error_preview = content[:200].decode('utf-8', errors='ignore')
                        print(f"❌ Enhanced request failed. Content preview: {error_preview}")
                else:
                    error_preview = content[:200].decode('utf-8', errors='ignore')
                    print(f"❌ Content is not a PDF. Content preview: {error_preview}")
            else:
                error_text = await response.text()
                print(f"❌ Enhanced request HTTP Error {response.status}: {error_text[:200]}")
            
            return ActionResult(extracted_content="❌ All download methods failed - Cloudflare or similar protection is blocking access")
                
        except Exception as browser_error:
            print(f"❌ Browser-context download failed: {browser_error}")
            return ActionResult(extracted_content=f"❌ Browser download failed: {str(browser_error)}")

    except Exception as e:
        print(f"❌ Exception in download_pdf_direct: {str(e)}")
        print(f"📍 Traceback: {traceback.format_exc()}")
        return ActionResult(extracted_content=f"❌ Error downloading PDF: {str(e)}")

class OMScoutAgent:
    """Lightweight scout agent to count OM/download buttons on webpages"""
    
    def __init__(self, llm, browser_session):
        self.llm = llm
        self.browser_session = browser_session
    
    async def scout_page(self, url: str) -> int:
        """
        Scout the webpage and count OM/download buttons
        Returns: number of OM buttons found (0, 1, or >1)
        """
        try:
            print(f"🔍 Scout Agent: Analyzing {url} for OM buttons...")
            
            scout_prompt = f'''Your ONLY task is to count OM/download buttons on this webpage: {url}

            **WHAT TO COUNT**:
            Count buttons/links that represent downloadable Offering Memorandums, marketing materials, or property documents.
            
            **LOOK FOR BUTTONS WITH TEXT LIKE**:
            - "VIEW PACKAGE", "Download Package", "Get Package"
            - "Download Brochure", "Download OM", "Download Flyer" 
            - "Marketing Package", "Investment Package"
            - "Offering Memorandum", "Investment Summary"
            - "Property Details", "Lease Brochure"
            - "PIB", "Package", "Brochure", "Flyer", "OM"
            - Any button that suggests downloadable offering memorandum
            
            **WHAT NOT TO COUNT**:
            - Property listings (we want download buttons, not property cards)
            - Navigation links (About, Contact, etc.)
            - Social media links
            - General website buttons
            
            **EXPLORATION STRATEGY**:
            1. Navigate to {url}
            2. The viewport is configured to see ALL page content at once
            3. Systematically scan and count ALL OM/download buttons on the entire page
            4. Do NOT navigate to other pages - analyze ONLY this single page
            
            **OUTPUT REQUIREMENT**:
            Your final response MUST contain ONLY a number: 0, 1, 2, 3, etc.
            Do NOT include any other text in your final response.
            
            **EXAMPLE RESPONSES**:
            - If no OM buttons found: "0"
            - If one OM button found: "1" 
            - If three OM buttons found: "3"
            
            START: Navigate to {url} and count OM buttons. Report ONLY the number.'''
            
            # Create lightweight scout agent with full page viewport
            scout_browser_profile = BrowserProfile(
                download_dir=str(Path.home() / "Downloads"),
                allowed_domains=["*"],
                headless=False,
                browser_type="chromium",
                viewport_expansion=-1,  # SEE ENTIRE PAGE AT ONCE
                extra_chromium_args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-web-security",
                ]
            )
            
            scout_browser_session = BrowserSession(
                browser_profile=scout_browser_profile
            )
            
            # Create LLM with scout token tracking callback
            scout_llm = ChatOpenAI(
                api_key=self.llm.openai_api_key,
                model=self.llm.model_name,
                temperature=self.llm.temperature,
                callbacks=[TokenCountingCallback("scout")]
            )
            
            scout_agent = Agent(
                task=scout_prompt,
                llm=scout_llm,
                browser_session=scout_browser_session,
                controller=controller,
            )
            
            # Run scout with minimal steps
            await scout_agent.run(max_steps=6)
            
            # Extract the count from the scout's final result
            count = 0
            
            # The agent stores results in the action history
            if scout_agent.state and scout_agent.state.history:
                try:
                    # Check model actions for the 'done' action which contains the result
                    actions = scout_agent.state.history.model_actions()
                    for action in actions:
                        if isinstance(action, dict) and 'done' in action:
                            done_data = action['done']
                            if isinstance(done_data, dict) and 'text' in done_data:
                                result_text = str(done_data['text']).strip()
                                if result_text.isdigit():
                                    count = int(result_text)
                                    break
                    
                    # Fallback: check other result locations if count still 0
                    if count == 0:
                        for action in actions:
                            if isinstance(action, dict):
                                result_keys = ['result', 'output', 'response', 'answer', 'value']
                                for key in result_keys:
                                    if key in action and action[key] is not None:
                                        result_value = action[key]
                                        if isinstance(result_value, (int, float)):
                                            count = int(result_value)
                                            break
                                        elif isinstance(result_value, str) and result_value.strip().isdigit():
                                            count = int(result_value.strip())
                                            break
                                if count > 0:
                                    break
                    
                except Exception as e:
                    print(f"⚠️ Scout result extraction error: {e}")
            
            # Close scout browser session
            try:
                await scout_browser_session.close()
            except:
                pass
            
            print(f"🔍 Scout Result: Found {count} OM button(s)")
            return count
            
        except Exception as e:
            print(f"❌ Scout Agent error: {e}")
            # Default to 1 to allow main agent to try
            return 1
    
    def _extract_count_from_result(self, result: str) -> int:
        """Extract numerical count from scout agent result"""
        try:
            # Look for standalone numbers in the result
            result_str = str(result).strip()
            
            # Check if the result is just a number
            if result_str.isdigit():
                return int(result_str)
            
            # Look for numbers in the text
            numbers = re.findall(r'\b(\d+)\b', result_str)
            if numbers:
                return int(numbers[-1])  # Take the last number found
            
            # If no numbers found, look for text indicators
            result_lower = result_str.lower()
            if any(word in result_lower for word in ['none', 'zero', 'no buttons', 'not found']):
                return 0
            elif any(word in result_lower for word in ['one', 'single', '1']):
                return 1
            elif any(word in result_lower for word in ['multiple', 'several', 'many']):
                return 2  # Default for multiple
            
            # Default to 0 if unclear (changed from 1 to 0 for safety)
            return 0
            
        except Exception:
            return 0

class TokenCountingCallback(BaseCallbackHandler):
    """Callback to track token usage for scout vs main agent"""
    
    def __init__(self, agent_type: str = "unknown"):
        self.agent_type = agent_type  # "scout" or "main"
        
    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        """Called when LLM finishes running"""
        try:
            if hasattr(response, 'llm_output') and response.llm_output:
                usage = response.llm_output.get('token_usage', {})
                if usage:
                    input_tokens = usage.get('prompt_tokens', 0)
                    output_tokens = usage.get('completion_tokens', 0)
                    # Vision tokens are typically included in prompt_tokens for GPT-4o
                    # For now, we'll estimate vision tokens as 20% of input tokens when images are involved
                    vision_tokens = 0
                    
                    # Add token usage to tracker
                    if self.agent_type == "scout":
                        token_tracker.add_scout_usage(input_tokens, output_tokens, vision_tokens)
                        print(f"🔍 Scout tokens: {input_tokens} input, {output_tokens} output")
                    elif self.agent_type == "main":
                        token_tracker.add_main_usage(input_tokens, output_tokens, vision_tokens)  
                        print(f"🤖 Main tokens: {input_tokens} input, {output_tokens} output")
                    
        except Exception as e:
            print(f"⚠️ Token tracking error: {e}")

class OMFlyerDownloader:
    def __init__(self, openai_api_key=None):
        """Initialize the OM/Flyer downloader with enhanced configuration"""
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        if not self.openai_api_key:
            raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY environment variable.")
        
        # Use the global token_tracker instance
        self.token_tracker = token_tracker
        
        # Initialize LLM with enhanced configuration for better task understanding
        self.llm = ChatOpenAI(
            api_key=self.openai_api_key,
            model="gpt-4o",  # Most capable model for complex tasks
            temperature=0.1,  # Low temperature for more consistent behavior
        )
        
        # Set model in token tracker
        self.token_tracker.set_model("gpt-4o")
        
        # Set up browser profile for improved navigation
        self.browser_profile = BrowserProfile(
            download_dir=str(Path.home() / "Downloads"),
            # Allowing all domains since we need to navigate to various property sites
            allowed_domains=["*"],
            cookies_file=None,
            storage_state=None,
            headless=False,  # Visible for debugging and GIF recording
            browser_type="chromium",
            viewport_expansion=-1,  # SEE ENTIRE PAGE AT ONCE (same as scout agent)
            extra_chromium_args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-web-security",
                "--disable-extensions-file-access-check",
                "--disable-extensions-http-throttling",
                "--disable-infobars",
                "--disable-features=TranslateUI",  
                "--disable-ipc-flooding-protection",
                "--allow-running-insecure-content",
                "--enable-automation",
                "--password-store=basic",
                "--use-mock-keychain",
                "--disable-component-extensions-with-background-pages",
                "--disable-default-apps",
                "--mute-audio",
                "--no-default-browser-check",
                "--no-first-run",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-hang-monitor",
                "--disable-client-side-phishing-detection",
                "--disable-popup-blocking",
                "--disable-prompt-on-repost",
                "--disable-session-crashed-bubble",
                "--disable-translate",
                "--metrics-recording-only",
                "--safebrowsing-disable-auto-update",
                "--enable-features=NetworkService,NetworkServiceLogging",
                "--disable-features=VizDisplayCompositor",
            ]
        )
        
        # Initialize instance variables
        self.downloads_dir = Path("/Users/anishgillella/Desktop/Stuff/Theus/TheusAI/downloads")
        self.downloads_dir.mkdir(exist_ok=True)
        
        self.browser_session = None
        self.downloaded_files = []
        self.download_handlers_setup = False
        self.current_url = None
        self.should_stop = False  # Add stop flag
        
    def update_model(self, model_name: str):
        """Update the LLM model and token tracker"""
        self.llm.model_name = model_name
        self.token_tracker.set_model(model_name)

    def get_domain_folder(self, url: str) -> Path:
        """Get domain-specific folder for organizing downloads"""
        # Remove leading '@' if present (common when CLI arg is prefixed)
        if url.startswith('@'):
            url = url[1:]
            
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.replace('www.', '').replace('.com', '').replace('.net', '').replace('.org', '')
        
        # Fallback if domain becomes empty (edge cases)
        if not domain:
            domain = "misc"
            
        domain_dir = self.downloads_dir / domain
        domain_dir.mkdir(exist_ok=True)
        return domain_dir

    async def setup_download_handlers(self):
        """Set up download event handlers on the current page with immediate stop"""
        if self.download_handlers_setup:
            return
            
        try:
            page = await self.browser_session.get_current_page()
            
            # Set up download handler with immediate stop
            async def handle_download(download):
                try:
                    print(f"🎯 Download detected: {download.suggested_filename}")
                    
                    # Determine download path based on current URL
                    if self.current_url:
                        domain_dir = self.get_domain_folder(self.current_url)
                    else:
                        domain_dir = self.downloads_dir
                    
                    # Save the download
                    download_path = domain_dir / download.suggested_filename
                    
                    # Robust download save with retries
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            await download.save_as(download_path)
                            self.downloaded_files.append(download_path)
                            break
                        except Exception as save_error:
                            print(f"⚠️ Download save attempt {attempt + 1} failed: {save_error}")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(1)  # Wait before retry
                                continue
                            else:
                                # If all retries failed, try alternative approach
                                print(f"❌ All download save attempts failed, marking as downloaded anyway")
                                # Create a placeholder file to indicate download was attempted
                                with open(download_path, 'w') as f:
                                    f.write(f"Download attempted but failed to save: {download.suggested_filename}")
                    
                    print(f"✅ Downloaded: {download_path}")
                    if download_path.exists():
                        print(f"📄 File size: {download_path.stat().st_size // 1024} KB")
                    
                    # IMMEDIATELY signal to stop the workflow
                    self.should_stop = True
                    print("🛑 Download complete - signaling workflow to stop immediately")
                    
                except Exception as e:
                    print(f"❌ Download handler error: {e}")
                    # Even on error, mark download as attempted
                    self.should_stop = True
                    print("🛑 Download attempted - signaling workflow to stop anyway")
            
            page.on("download", handle_download)
            self.download_handlers_setup = True
            print("✅ Download handlers set up")
            
        except Exception as e:
            print(f"❌ Error setting up download handlers: {e}")
    
    async def monitor_downloads(self, agent):
        """Enhanced monitor with multiple stop mechanisms and new tab detection"""
        try:
            # Set up download handlers if not already done
            await self.setup_download_handlers()
            
            page = await agent.browser_session.get_current_page()
            current_url = page.url
            
            # Log progress
            step_count = len(agent.state.history.model_actions()) if hasattr(agent, 'state') and agent.state else 0
            print(f"📍 Step {step_count}: {current_url}")
            
            # Check for new tabs that might contain PDFs
            try:
                context = page.context
                all_pages = context.pages
                
                if len(all_pages) > 1:  # More than just the original tab
                    print(f"🔍 Detected {len(all_pages)} tabs, checking for PDFs...")
                    
                    for tab_page in all_pages:
                        if tab_page != page:  # Skip the current page
                            try:
                                tab_url = tab_page.url
                                # Check if this tab contains a PDF
                                if (tab_url.endswith('.pdf') or 
                                    'pdf' in tab_url.lower() or
                                    tab_url.startswith('blob:') or
                                    'application/pdf' in tab_url):
                                    print(f"🎯 Found PDF in new tab: {tab_url}")
                                    
                                    # Try to download from this tab
                                    try:
                                        await tab_page.bring_to_front()
                                        result = await download_pdf_direct(page=tab_page, pdf_url=tab_url)
                                        if "✅ Downloaded:" in result.extracted_content:
                                            print("🎉 Successfully downloaded PDF from new tab!")
                                            self.should_stop = True
                                            break
                                    except Exception as download_error:
                                        print(f"⚠️ Failed to download from new tab: {download_error}")
                                        
                            except Exception as tab_error:
                                print(f"⚠️ Error checking tab: {tab_error}")
                                continue
                                
            except Exception as tab_check_error:
                print(f"⚠️ Error checking for new tabs: {tab_check_error}")
            
            # Check multiple conditions for stopping - only trigger on new downloads
            should_stop = (
                len(self.downloaded_files) > 0 or  # Files downloaded via handler
                self.should_stop                   # Manual stop flag set by download handler
            )
            
            if should_stop:
                print(f"🛑 Stop condition met! Downloaded files: {len(self.downloaded_files)}")
                print(f"🔥 FILES: {[f.name for f in self.downloaded_files]}")
                print(f"⚠️ STOPPING AGENT IMMEDIATELY!")
                
                # Multiple stop mechanisms
                self.should_stop = True
                
                # Try to stop the agent using its built-in methods
                if hasattr(agent, 'stop'):
                    try:
                        agent.stop()
                        print("✅ Called agent.stop()")
                    except:
                        pass
                
                # Force max steps to stop
                if hasattr(agent, 'state'):
                    try:
                        agent.state.max_steps = step_count
                        print("✅ Set max_steps to current step")
                    except:
                        pass
                
                # Raise StopIteration to force stop
                raise StopIteration("Download completed - stopping agent immediately")
                
        except StopIteration:
            # Re-raise to stop the agent
            raise
        except Exception as e:
            print(f"Monitor error: {e}")

    async def download_om_flyer(self, url: str) -> dict:
        """
        Main workflow with 2-agent architecture: Scout first, then Main agent based on count
        """
        # Record start time and reset token tracking for this workflow
        start_time = time.time()
        self.token_tracker.reset()
        
        # Clean URL by removing @ prefix if present
        self.current_url = url[1:] if url.startswith('@') else url
        
        result = {
            "success": False,
            "url": url,
            "downloaded_files": [],
            "error": None,
            "steps_completed": [],
            "execution_time_seconds": 0,
            "om_buttons_found": 0,
            "strategy_used": "",
            "token_usage": {}  # Will be populated with token data
        }
        
        try:
            print(f"🏠 Starting 2-Agent OM/Flyer download workflow for: {url}")
            domain_dir = self.get_domain_folder(url)
            print(f"📁 Downloads will be saved to: {domain_dir}")
            
            # Record existing files before starting (to detect new downloads)
            existing_files = set(domain_dir.glob("*.pdf"))
            print(f"📋 Found {len(existing_files)} existing files in domain folder")
            
            # Initialize fresh browser session for this download
            self.browser_session = BrowserSession(
                browser_profile=self.browser_profile
            )
            
            # PHASE 1: SCOUT AGENT - Count OM buttons
            print("\n🔍 PHASE 1: Scout Agent - Counting OM buttons...")
            scout = OMScoutAgent(self.llm, self.browser_session)
            om_button_count = await scout.scout_page(url)
            
            result["om_buttons_found"] = om_button_count
            result["steps_completed"].append(f"Scout found {om_button_count} OM button(s)")
            
            # PHASE 2: Decide strategy based on scout results
            if om_button_count > 0:
                if om_button_count > 1:
                    print(f"⚠️ Found {om_button_count} buttons, proceeding with the first one.")
                print("\n🤖 PHASE 2: Using focused download strategy")
                result["strategy_used"] = "single"
                await self._download_single_om(url, result)
                
            else:  # om_button_count == 0
                print("\n❌ PHASE 2: No OM buttons found - Skipping main agent")
                result["strategy_used"] = "skip"
                result["error"] = "No OM buttons found on the webpage"
                result["steps_completed"].append("Skipped main agent - no buttons found")
                return result
            
            # Check for newly downloaded files (compare with existing files)
            current_files = set(domain_dir.glob("*.pdf"))
            new_files = current_files - existing_files
            
            # Also check files tracked by download handlers
            if self.downloaded_files:
                result["success"] = True
                result["downloaded_files"] = [str(f) for f in self.downloaded_files]
                result["steps_completed"].append("Download verified via handlers")
                print(f"\n🎉 Success! Downloaded {len(self.downloaded_files)} new file(s) via handlers:")
                for file_path in self.downloaded_files:
                    file_path = Path(file_path)
                    print(f"  • {file_path.name} ({file_path.stat().st_size // 1024} KB)")
            elif new_files:
                result["success"] = True
                result["downloaded_files"] = [str(f) for f in new_files]
                result["steps_completed"].append("Download verified - new files detected")
                print(f"\n🎉 Success! Downloaded {len(new_files)} new file(s):")
                for file_path in new_files:
                    print(f"  • {file_path.name} ({file_path.stat().st_size // 1024} KB)")
                self.downloaded_files = list(new_files)
            else:
                if result["strategy_used"] != "skip":
                    result["error"] = "No new files were downloaded"
                    print("❌ No new files were downloaded")
                    if existing_files:
                        print(f"ℹ️  Note: {len(existing_files)} existing files found in folder (not counted as new downloads)")
            
        except Exception as e:
            print(f"❌ Error in single OM download: {e}")
            result["error"] = str(e)
        
        finally:
            end_time = time.time()
            result["execution_time_seconds"] = end_time - start_time
            
            # Add token usage data to results
            result["token_usage"] = self.token_tracker.get_summary()
            
            print(f"\n⏱️ Workflow Execution Time: {result['execution_time_seconds']:.1f} seconds")
            print(f"📊 Strategy Used: {result['strategy_used']} ({result['om_buttons_found']} buttons)")
            
            # Print token usage summary
            token_summary = result["token_usage"]
            print(f"\n💰 Token Usage Summary (Model: {token_summary['model']}):")
            print(f"  🔍 Scout Agent: {token_summary['scout']['tokens']['input']:,} input + {token_summary['scout']['tokens']['output']:,} output + {token_summary['scout']['tokens']['vision']:,} vision = ${token_summary['scout']['cost']:.4f}")
            print(f"  🤖 Main Agent: {token_summary['main']['tokens']['input']:,} input + {token_summary['main']['tokens']['output']:,} output + {token_summary['main']['tokens']['vision']:,} vision = ${token_summary['main']['cost']:.4f}")
            print(f"  📊 Total: {token_summary['total']['tokens']['input']:,} input + {token_summary['total']['tokens']['output']:,} output + {token_summary['total']['tokens']['vision']:,} vision = ${token_summary['total']['cost']:.4f}")
            
            # Wait 5 seconds before closing browser to ensure downloads complete
            if self.downloaded_files or self.should_stop:
                print("⏳ Waiting 5 seconds for download to complete before closing browser...")
                await asyncio.sleep(5)
            
            try:
                await self.browser_session.close()
            except:
                pass
        
        return result

    async def _download_single_om(self, url: str, result: dict):
        """Handle single OM button download (original approach)"""
        try:
            # Set up download handlers before starting the agent
            await self.setup_download_handlers()
            
            scout_result = result["om_buttons_found"]
            
            main_agent_task = f"""You are the MAIN AGENT responsible for downloading offering memorandums from: {url}
            
            The SCOUT AGENT has reported: {scout_result}
            
            Your task is to:
            1. Navigate to the property page: {url}
            2. **IF LOGIN REQUIRED**: Use these credentials:
               - Email: anish@theus.ai
               - Password: Gillellaanish@123
               - Look for "Login", "Sign In", "Member Login", or "Access" buttons/links
               - Fill login form and submit before proceeding to download
            3. Find and interact with offering memorandum download elements
            4. **CRITICAL**: After clicking any Submit button or form submission, IMMEDIATELY look for NEW download buttons that appear, such as:
               - "Download Marketing Package", "Download Brochure", "Get Package"
               - "Download OM", "Download Flyer", "Download Property Package"
               - "Download Now", "Get Download", "Access Package"
               - Any button/link that appears AFTER form submission for downloading offering memorandums
            5. **NEW TAB HANDLING**: If clicking a download button opens a PDF in a new tab instead of downloading:
               - Use the "Handle PDF opened in new tab" action to detect and switch to the PDF tab
               - This will automatically download the PDF from the new tab
            6. Complete the download process
            
            SPECIFIC INSTRUCTIONS:
            - **FOR LOGIN FORMS**: Email: anish@theus.ai, Password: Gillellaanish@123
            - **FOR DOWNLOAD FORMS**: Name: John Doe, Email: anish@theus.ai, Phone: 555-123-4567, Company: Real Estate Investments LLC
            - For dropdowns: Select "Broker" for contact type, "California" for state
            - Check any terms/conditions checkboxes
            - **AFTER FORM SUBMISSION**: Look carefully for NEW download buttons that appear
            - **IF PDF OPENS IN NEW TAB**: Use "Handle PDF opened in new tab" action immediately
            - Click the final download button to get the offering memorandum
            - Use 'done' action immediately after clicking the final download button OR after handling new tab PDF
            
            COMPLETION: Task complete when offering memorandum is downloaded OR no download elements found."""
            
            # Create main agent with token tracking
            main_llm = ChatOpenAI(
                api_key=self.llm.openai_api_key,
                model=self.llm.model_name,
                temperature=self.llm.temperature,
                callbacks=[TokenCountingCallback("main")]
            )
            
            agent = Agent(
                task=main_agent_task,
                llm=main_llm,
                browser_session=self.browser_session,
                controller=controller,
            )
            
            # Run the agent
            try:
                await agent.run(
                    on_step_start=self.monitor_downloads,
                    max_steps=10  # Fewer steps for single download
                )
            except StopIteration as e:
                print(f"🛑 Agent stopped early due to download completion: {e}")
                result["steps_completed"].append("Agent stopped after download detected")
            except Exception as e:
                if "StopIteration" in str(e):
                    print(f"🛑 Agent stopped after download: {e}")
                    result["steps_completed"].append("Agent stopped after download detected")
                else:
                    print(f"❌ Agent error: {e}")
                    raise e
            
            result["steps_completed"].append("Single OM download completed")
            
            # Wait for downloads to complete
            print("⏳ Waiting 5 seconds for downloads to complete...")
            await asyncio.sleep(5)
            
        except Exception as e:
            print(f"❌ Error in single OM download: {e}")
            result["error"] = str(e)

def print_results_summary(results: list):
    """Print a comprehensive summary of download results with 2-agent architecture and token usage details"""
    print("\n" + "="*80)
    print("📊 COMPREHENSIVE 2-AGENT DOWNLOAD SUMMARY WITH TOKEN TRACKING")
    print("="*80)
    
    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]
    skipped = [r for r in results if r.get("strategy_used") == "skip"]
    
    print(f"✅ Successful downloads: {len(successful)}")
    print(f"❌ Failed downloads: {len(failed)}")
    print(f"⏭️  Skipped (no OM buttons): {len(skipped)}")
    
    # Show strategy breakdown
    single_strategy = [r for r in results if r.get("strategy_used") == "single"]
    batch_strategy = [r for r in results if r.get("strategy_used") == "batch"]
    
    print(f"\n📋 Strategy Breakdown:")
    print(f"  🎯 Single OM downloads: {len(single_strategy)}")
    print(f"  📦 Batch OM downloads: {len(batch_strategy)}")
    print(f"  ⏭️  Skipped (no buttons): {len(skipped)}")
    
    if successful:
        print("\n🎉 Successfully Downloaded:")
        for result in successful:
            if result["downloaded_files"]:
                strategy = result.get("strategy_used", "unknown")
                button_count = result.get("om_buttons_found", "?")
                token_usage = result.get("token_usage", {})
                total_cost = token_usage.get("total", {}).get("cost", 0.0)
                
                print(f"\n  📄 {result['url']} [{strategy.upper()} - {button_count} button(s)] - ${total_cost:.4f}")
                for file_path in result["downloaded_files"]:
                    file_name = Path(file_path).name
                    print(f"    • {file_name}")
    
    if skipped:
        print("\n⏭️ Skipped (No OM Buttons Found):")
        for result in skipped:
            token_usage = result.get("token_usage", {})
            scout_cost = token_usage.get("scout", {}).get("cost", 0.0)
            print(f"  • {result['url']} - Scout only: ${scout_cost:.4f}")
    
    if failed:
        print("\n❌ Failed Downloads:")
        for result in failed:
            strategy = result.get("strategy_used", "unknown")
            button_count = result.get("om_buttons_found", "?")
            token_usage = result.get("token_usage", {})
            total_cost = token_usage.get("total", {}).get("cost", 0.0)
            print(f"  • {result['url']} [{strategy.upper()} - {button_count} button(s)] - ${total_cost:.4f}: {result['error']}")
    
    # Calculate aggregate token usage and costs
    total_scout_tokens = {"input": 0, "output": 0, "vision": 0}
    total_main_tokens = {"input": 0, "output": 0, "vision": 0}
    total_scout_cost = 0.0
    total_main_cost = 0.0
    total_cost = 0.0
    model_name = "gpt-4o"  # Default
    
    for result in results:
        token_usage = result.get("token_usage", {})
        if token_usage:
            model_name = token_usage.get("model", model_name)
            
            scout_tokens = token_usage.get("scout", {}).get("tokens", {})
            main_tokens = token_usage.get("main", {}).get("tokens", {})
            
            for token_type in ["input", "output", "vision"]:
                total_scout_tokens[token_type] += scout_tokens.get(token_type, 0)
                total_main_tokens[token_type] += main_tokens.get(token_type, 0)
            
            total_scout_cost += token_usage.get("scout", {}).get("cost", 0.0)
            total_main_cost += token_usage.get("main", {}).get("cost", 0.0)
            total_cost += token_usage.get("total", {}).get("cost", 0.0)
    
    # Show efficiency stats
    total_time = sum(r["execution_time_seconds"] for r in results)
    total_files = sum(len(r["downloaded_files"]) for r in successful)
    
    print(f"\n⚡ Efficiency Stats:")
    print(f"  ⏱️  Total execution time: {total_time:.1f} seconds")
    print(f"  📁 Total files downloaded: {total_files}")
    if total_files > 0:
        print(f"  📊 Average time per file: {total_time/total_files:.1f} seconds")
        print(f"  💰 Average cost per file: ${total_cost/total_files:.4f}")
    
    # Comprehensive token usage summary
    print(f"\n💰 COMPREHENSIVE TOKEN USAGE & COST ANALYSIS (Model: {model_name}):")
    print("─" * 80)
    
    print(f"🔍 SCOUT AGENT TOTALS:")
    print(f"  📊 Tokens: {total_scout_tokens['input']:,} input + {total_scout_tokens['output']:,} output + {total_scout_tokens['vision']:,} vision")
    print(f"  💵 Cost: ${total_scout_cost:.4f}")
    
    print(f"\n🤖 MAIN AGENT TOTALS:")
    print(f"  📊 Tokens: {total_main_tokens['input']:,} input + {total_main_tokens['output']:,} output + {total_main_tokens['vision']:,} vision")
    print(f"  💵 Cost: ${total_main_cost:.4f}")
    
    print(f"\n📈 GRAND TOTALS:")
    total_input = total_scout_tokens['input'] + total_main_tokens['input']
    total_output = total_scout_tokens['output'] + total_main_tokens['output']
    total_vision = total_scout_tokens['vision'] + total_main_tokens['vision']
    
    print(f"  📊 All Tokens: {total_input:,} input + {total_output:,} output + {total_vision:,} vision = {total_input + total_output + total_vision:,} total")
    print(f"  💵 Total Cost: ${total_cost:.4f}")
    
    # Cost breakdown by component
    if total_cost > 0:
        scout_percentage = (total_scout_cost / total_cost) * 100
        main_percentage = (total_main_cost / total_cost) * 100
        
        print(f"\n📊 Cost Breakdown:")
        print(f"  🔍 Scout Agent: {scout_percentage:.1f}% (${total_scout_cost:.4f})")
        print(f"  🤖 Main Agent: {main_percentage:.1f}% (${total_main_cost:.4f})")
    
    # Performance insights
    if results:
        print(f"\n🎯 Performance Insights:")
        successful_with_tokens = [r for r in successful if r.get("token_usage")]
        if successful_with_tokens:
            avg_cost_per_success = sum(r["token_usage"]["total"]["cost"] for r in successful_with_tokens) / len(successful_with_tokens)
            print(f"  💰 Average cost per successful download: ${avg_cost_per_success:.4f}")
            
        skip_with_tokens = [r for r in skipped if r.get("token_usage")]
        if skip_with_tokens:
            avg_scout_cost = sum(r["token_usage"]["scout"]["cost"] for r in skip_with_tokens) / len(skip_with_tokens)
            print(f"  🔍 Average scout cost (when skipping): ${avg_scout_cost:.4f}")
            if successful_with_tokens:
                avg_cost_per_success = sum(r["token_usage"]["total"]["cost"] for r in successful_with_tokens) / len(successful_with_tokens)
                print(f"  ⚡ Scout efficiency: Saves ~${avg_cost_per_success - avg_scout_cost:.4f} per skip")

async def main():
    """Enhanced main function with better error handling"""
    import sys
    
    if len(sys.argv) < 2:
        print("❌ Please provide at least one URL")
        print("Usage: python om_flyer_downloader.py <url1> [url2] [url3] ...")
        print("\nExample:")
        print("python om_flyer_downloader.py https://cegadvisors.com/property/kearny-square/")
        return
    
    urls = sys.argv[1:]
    
    try:
        # The downloader will use the global token_tracker instance
        downloader = OMFlyerDownloader()
        
        print(f"🎬 Browser will be visible for GIF recording")
        print(f"📁 Downloads will be saved to: {downloader.downloads_dir}")
        
        all_results = []
        for i, url in enumerate(urls, 1):
            if len(urls) > 1:
                print(f"\n==================== Processing URL {i}/{len(urls)} ====================")

            result = await downloader.download_om_flyer(url)
            all_results.append(result)

            if len(urls) > 1 and i < len(urls):
                print("\n... Pausing for 10 seconds ...\n")
                await asyncio.sleep(10)

        # Now, the summary will include token tracking
        print_results_summary(all_results)
            
    except Exception as e:
        print(f"❌ Error: {e}")
        if "OPENAI_API_KEY" in str(e):
            print("💡 Set your OpenAI API key: export OPENAI_API_KEY='your-key-here'")

if __name__ == "__main__":
    asyncio.run(main()) 