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

# Load environment variables
load_dotenv()

# Create controller for custom actions
controller = Controller()

# Custom action to download PDF directly using browser context navigation
@controller.action('Download PDF directly from URL')
async def download_pdf_direct(page: Page) -> ActionResult:
    """
    Download PDF directly from the current page URL using browser context navigation
    to bypass Cloudflare and other bot detection systems
    """
    try:
        current_url = page.url
        print(f"🔍 Attempting to download PDF from: {current_url}")
        
        # More flexible PDF detection - check URL or content type
        is_pdf_url = (current_url.endswith('.pdf') or 
                     'pdf' in current_url.lower() or
                     '/uploads/' in current_url)
        
        if not is_pdf_url:
            print(f"❌ URL doesn't appear to be a PDF: {current_url}")
            return ActionResult(extracted_content=f"❌ Current page URL doesn't appear to be a PDF: {current_url}")
        
        # Set up downloads directory
        downloads_dir = Path("/Users/anishgillella/Desktop/Stuff/Theus/TheusAI/downloads")
        downloads_dir.mkdir(exist_ok=True, parents=True)
        print(f"📁 Downloads directory: {downloads_dir}")
        
        # Extract filename from URL
        filename = current_url.split('/')[-1]
        if '?' in filename:
            filename = filename.split('?')[0]  # Remove query parameters
        if not filename.endswith('.pdf') and not '.pdf' in filename:
            filename += '.pdf'
        
        # Clean filename
        clean_filename = filename.replace('%20', '-').replace(' ', '-').replace('%2B', '+')
        download_path = downloads_dir / clean_filename
        print(f"💾 Target file path: {download_path}")
        
        # Enhanced browser-context download method
        print("🌐 Starting download using enhanced browser context...")
        
        try:
            # Method 1: Browser-native download with session preservation
            context = page.context
            
            # Check if already on PDF page, if not navigate to it
            if page.url != current_url:
                print(f"🔄 Navigating to PDF URL: {current_url}")
                await page.goto(current_url, wait_until='networkidle')
                await page.wait_for_timeout(2000)  # Allow page to fully load
            
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
                
                # Save to our downloads directory
                final_path = downloads_dir / (download.suggested_filename or clean_filename)
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
                pdf_buffer = await page.evaluate("""
                    async () => {
                        try {
                            const response = await fetch(window.location.href);
                            if (response.ok) {
                                const arrayBuffer = await response.arrayBuffer();
                                const bytes = new Uint8Array(arrayBuffer);
                                return Array.from(bytes);
                            }
                        } catch (e) {
                            console.error('Fetch failed:', e);
                        }
                        return null;
                    }
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
                error_text = await response.text()
                print(f"❌ Enhanced request HTTP Error {response.status}: {error_text[:200]}")
            
            return ActionResult(extracted_content="❌ All download methods failed - Cloudflare or similar protection is blocking access")
                
        except Exception as browser_error:
            print(f"❌ Browser-context download failed: {browser_error}")
            return ActionResult(extracted_content=f"❌ Browser download failed: {str(browser_error)}")

    except Exception as e:
        print(f"❌ Exception in download_pdf_direct: {str(e)}")
        import traceback
        print(f"📍 Traceback: {traceback.format_exc()}")
        return ActionResult(extracted_content=f"❌ Error downloading PDF: {str(e)}")

# Generic dropdown handler that works for any dropdown type
@controller.action('Select option from any dropdown')
async def select_dropdown_option_generic(dropdown_identifier: str, option_to_select: str, page: Page) -> ActionResult:
    """
    Generic action to handle ANY dropdown type and select specified option
    
    Args:
        dropdown_identifier: Text/attribute to identify the dropdown (e.g., "Contact Type", "State", "City")
        option_to_select: The option text to select (e.g., "Broker", "California", "New York")
    """
    try:
        await page.wait_for_timeout(1000)
        
        # METHOD 1: Try native HTML select elements first
        native_select_selectors = [
            f"select:has(option:text('{option_to_select}'))",
            f"select[name*='{dropdown_identifier.lower().replace(' ', '')}']",
            f"select[id*='{dropdown_identifier.lower().replace(' ', '')}']",
            f"select:near(text='{dropdown_identifier}')",
            "select", # Last resort - any select element
        ]
        
        for selector in native_select_selectors:
            try:
                dropdown = page.locator(selector)
                if await dropdown.count() > 0:
                    # Try selecting by label, value, or index
                    try:
                        await dropdown.select_option(label=option_to_select)
                        return ActionResult(extracted_content=f"✅ Selected '{option_to_select}' from native select using label")
                    except:
                        try:
                            await dropdown.select_option(value=option_to_select.lower())
                            return ActionResult(extracted_content=f"✅ Selected '{option_to_select}' from native select using value")
                        except:
                            try:
                                await dropdown.select_option(index=0)  # Select first option as fallback
                                return ActionResult(extracted_content=f"✅ Selected first option from native select as fallback")
                            except:
                                continue
            except:
                continue
        
        # METHOD 2: Custom dropdowns - find by identifier text
        dropdown_trigger_selectors = [
            f"*:has-text('{dropdown_identifier}'):visible",
            f"*:has-text('Select {dropdown_identifier}'):visible",
            "[placeholder*='{dropdown_identifier}']",
            "[aria-label*='{dropdown_identifier}']",
            f"[data-field*='{dropdown_identifier.lower().replace(' ', '')}']",
            f".{dropdown_identifier.lower().replace(' ', '-')} *",
            f"#{dropdown_identifier.lower().replace(' ', '-')} *",
        ]
        
        for trigger_selector in dropdown_trigger_selectors:
            try:
                trigger = page.locator(trigger_selector)
                if await trigger.count() > 0:
                    # Click to open dropdown
                    await trigger.first.click()
                    await page.wait_for_timeout(1500)
                    
                    # Try to find and click the option
                    option_selectors = [
                        f"text='{option_to_select}'",
                        f"*:has-text('{option_to_select}'):visible",
                        f"li:has-text('{option_to_select}')",
                        f"[data-value='{option_to_select}']",
                        f"[value='{option_to_select}']",
                        f"[value='{option_to_select.lower()}']",
                        f".option:has-text('{option_to_select}')",
                        f".dropdown-item:has-text('{option_to_select}')",
                        f"[role='option']:has-text('{option_to_select}')",
                    ]
                    
                    for option_selector in option_selectors:
                        try:
                            option = page.locator(option_selector)
                            if await option.count() > 0:
                                await option.first.click()
                                return ActionResult(extracted_content=f"✅ Selected '{option_to_select}' from custom dropdown using: {trigger_selector} → {option_selector}")
                        except:
                            continue
                            
                    # If specific option not found, try selecting first visible option
                    try:
                        first_option = page.locator("li:visible, .option:visible, [role='option']:visible").first
                        if await first_option.count() > 0:
                            await first_option.click()
                            return ActionResult(extracted_content=f"✅ Selected first available option from dropdown as fallback")
                    except:
                        pass
            except:
                continue
        
        # METHOD 3: Handle iframes
        try:
            frames = page.frames
            for frame in frames:
                try:
                    # Try native selects in iframe
                    iframe_select = frame.locator(f"select:has(option:text('{option_to_select}'))")
                    if await iframe_select.count() > 0:
                        await iframe_select.select_option(label=option_to_select)
                        return ActionResult(extracted_content=f"✅ Selected '{option_to_select}' from iframe native select")
                    
                    # Try custom dropdowns in iframe
                    iframe_trigger = frame.locator(f"*:has-text('{dropdown_identifier}'):visible")
                    if await iframe_trigger.count() > 0:
                        await iframe_trigger.first.click()
                        await page.wait_for_timeout(1000)
                        iframe_option = frame.locator(f"*:has-text('{option_to_select}'):visible")
                        if await iframe_option.count() > 0:
                            await iframe_option.first.click()
                            return ActionResult(extracted_content=f"✅ Selected '{option_to_select}' from iframe custom dropdown")
                except:
                    continue
        except:
            pass
        
        # METHOD 4: Keyboard navigation fallback
        try:
            # Find any element with the dropdown identifier and try keyboard navigation
            dropdown_element = page.locator(f"*:has-text('{dropdown_identifier}'):visible").first
            if await dropdown_element.count() > 0:
                await dropdown_element.click()
                await page.keyboard.press("ArrowDown")  # Open dropdown
                await page.wait_for_timeout(500)
                await page.keyboard.press("Enter")     # Select first option
                return ActionResult(extracted_content=f"✅ Selected option using keyboard navigation")
        except:
            pass
            
        return ActionResult(extracted_content=f"❌ Could not find or select '{option_to_select}' from '{dropdown_identifier}' dropdown")
        
    except Exception as e:
        return ActionResult(extracted_content=f"❌ Error in generic dropdown selection: {str(e)}")

# Keep the old specific action for backward compatibility, but make it use the generic one
@controller.action('Select Broker from Contact Type dropdown')
async def select_broker_from_contact_dropdown(page: Page) -> ActionResult:
    """Legacy action - uses generic dropdown handler"""
    return await select_dropdown_option_generic("Contact Type", "Broker", page)

# Generic checkbox handler for terms, conditions, agreements, etc.
@controller.action('Check terms and conditions checkbox')
async def check_terms_checkbox(page: Page) -> ActionResult:
    """Generic action to find and check terms and conditions checkboxes"""
    try:
        await page.wait_for_timeout(1000)
        
        # Multiple selectors for terms and conditions checkboxes
        checkbox_selectors = [
            "input[type='checkbox']:near(text*='terms')",
            "input[type='checkbox']:near(text*='conditions')", 
            "input[type='checkbox']:near(text*='agree')",
            "input[type='checkbox']:near(text*='accept')",
            "[type='checkbox']:has-text('accept')",
            "[type='checkbox']:has-text('terms')",
            "[type='checkbox']:has-text('conditions')",
            "label:has-text('accept') input[type='checkbox']",
            "label:has-text('terms') input[type='checkbox']",
            "label:has-text('conditions') input[type='checkbox']",
            "*:has-text('I accept') input[type='checkbox']",
            "*:has-text('Terms and Conditions') input[type='checkbox']",
            "input[type='checkbox']", # Fallback - any checkbox
        ]
        
        for selector in checkbox_selectors:
            try:
                checkbox = page.locator(selector)
                count = await checkbox.count()
                if count > 0:
                    # Check if already checked
                    is_checked = await checkbox.first.is_checked()
                    if not is_checked:
                        await checkbox.first.check()
                        return ActionResult(extracted_content=f"✅ Successfully checked checkbox using selector: {selector}")
                    else:
                        return ActionResult(extracted_content=f"✅ Checkbox already checked using selector: {selector}")
            except:
                continue
        
        # Alternative approach: Click on label text
        label_selectors = [
            "text='I accept the Terms and Conditions'",
            "*:has-text('I accept'):visible",
            "*:has-text('Terms and Conditions'):visible",
            "*:has-text('agree'):visible",
            "label:has-text('accept')",
            "label:has-text('terms')",
        ]
        
        for selector in label_selectors:
            try:
                label = page.locator(selector)
                if await label.count() > 0:
                    await label.first.click()
                    return ActionResult(extracted_content=f"✅ Clicked terms label using selector: {selector}")
            except:
                continue
                
        return ActionResult(extracted_content="❌ Could not find or check terms and conditions checkbox")
        
    except Exception as e:
        return ActionResult(extracted_content=f"❌ Error checking checkbox: {str(e)}")

# Custom action to handle iframe forms (especially for Knipp Wolf sites)
@controller.action('Handle iframe forms and downloads')
async def handle_iframe_forms(page: Page) -> ActionResult:
    """
    Detect and handle forms within iframes, common on sites like Knipp Wolf
    """
    try:
        print("🔍 Scanning for iframe forms...")
        
        # Wait for page to load completely
        await page.wait_for_load_state('networkidle')
        await page.wait_for_timeout(3000)
        
        # Get all iframes on the page
        iframes = await page.locator('iframe').all()
        print(f"📋 Found {len(iframes)} iframes on page")
        
        for i, iframe in enumerate(iframes):
            try:
                print(f"🔍 Checking iframe {i+1}/{len(iframes)}")
                
                # Get iframe source
                iframe_src = await iframe.get_attribute('src')
                print(f"📎 Iframe src: {iframe_src}")
                
                # Wait for iframe to load
                await page.wait_for_timeout(2000)
                
                # Get iframe content frame
                frame = await iframe.content_frame()
                if not frame:
                    print(f"❌ Could not access iframe {i+1} content")
                    continue
                
                # Wait for iframe content to load
                await frame.wait_for_load_state('networkidle', timeout=10000)
                
                # Look for download forms in iframe
                download_buttons = await frame.locator('button, input[type="submit"], a').all()
                for button in download_buttons:
                    button_text = await button.text_content() or ""
                    button_value = await button.get_attribute('value') or ""
                    
                    # Check if this looks like a download button
                    download_keywords = ['download', 'get', 'view', 'package', 'brochure', 'om', 'flyer', 'memorandum']
                    button_content = (button_text + " " + button_value).lower()
                    
                    if any(keyword in button_content for keyword in download_keywords):
                        print(f"🎯 Found potential download button in iframe: '{button_text or button_value}'")
                        
                        # Fill out form if present
                        await fill_iframe_form(frame)
                        
                        # Click the download button
                        await button.click()
                        print(f"✅ Clicked download button in iframe")
                        
                        # Wait for potential download or new tab
                        await page.wait_for_timeout(3000)
                        
                        return ActionResult(extracted_content=f"✅ Successfully interacted with iframe form and clicked download button")
                
            except Exception as iframe_error:
                print(f"⚠️ Error processing iframe {i+1}: {iframe_error}")
                continue
        
        return ActionResult(extracted_content="❌ No downloadable forms found in iframes")
        
    except Exception as e:
        print(f"❌ Error handling iframe forms: {e}")
        return ActionResult(extracted_content=f"❌ Error handling iframe forms: {e}")

async def fill_iframe_form(frame):
    """Helper function to fill forms within iframes"""
    try:
        print("📝 Filling iframe form...")
        
        # Common form fields to fill
        form_data = {
            "name": "John Doe",
            "firstname": "John", 
            "first_name": "John",
            "lastname": "Doe",
            "last_name": "Doe",
            "email": "johndoe@email.com",
            "phone": "555-123-4567",
            "company": "Real Estate Investments LLC",
            "organization": "Real Estate Investments LLC"
        }
        
        # Fill text inputs
        for field_name, value in form_data.items():
            selectors = [
                f'input[name*="{field_name}"]',
                f'input[id*="{field_name}"]',
                f'input[placeholder*="{field_name}"]'
            ]
            
            for selector in selectors:
                try:
                    field = frame.locator(selector).first
                    if await field.count() > 0:
                        await field.fill(value)
                        print(f"✅ Filled {field_name}: {value}")
                        break
                except:
                    continue
        
        # Handle dropdowns in iframe
        try:
            # Look for contact type dropdown
            contact_selects = await frame.locator('select').all()
            for select in contact_selects:
                select_name = await select.get_attribute('name') or ""
                if 'contact' in select_name.lower() or 'type' in select_name.lower():
                    try:
                        await select.select_option(label="Broker")
                        print("✅ Selected 'Broker' from contact type dropdown in iframe")
                        break
                    except:
                        try:
                            await select.select_option(label="Principal")
                            print("✅ Selected 'Principal' from contact type dropdown in iframe")
                            break
                        except:
                            continue
        except Exception as dropdown_error:
            print(f"⚠️ Could not handle dropdowns in iframe: {dropdown_error}")
        
        # Check terms checkbox if present
        try:
            checkboxes = await frame.locator('input[type="checkbox"]').all()
            for checkbox in checkboxes:
                checkbox_label = await checkbox.get_attribute('name') or ""
                if 'terms' in checkbox_label.lower() or 'agree' in checkbox_label.lower():
                    await checkbox.check()
                    print("✅ Checked terms checkbox in iframe")
                    break
        except Exception as checkbox_error:
            print(f"⚠️ Could not handle checkboxes in iframe: {checkbox_error}")
            
    except Exception as e:
        print(f"❌ Error filling iframe form: {e}")

class OMFlyerDownloader:
    def __init__(self, openai_api_key=None):
        """Initialize the OM/Flyer downloader with Browser Use agent"""
        self.api_key = openai_api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY environment variable or pass it directly.")
        
        # Set up downloads directory
        self.downloads_dir = Path("/Users/anishgillella/Desktop/Stuff/Theus/TheusAI/downloads")
        self.downloads_dir.mkdir(exist_ok=True, parents=True)
        
        # Initialize LLM
        self.llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0.0,
            api_key=self.api_key
        )
        
        # Configure browser profile with iframe support
        self.browser_profile = BrowserProfile(
            headless=False,
            viewport={"width": 1280, "height": 1024},
            wait_for_network_idle_page_load_time=3.0,
            highlight_elements=True,
            # Enhanced iframe support for sites like Knipp Wolf
            disable_security=True,  # Allow cross-origin iframe access
            disable_web_security=True,  # Disable web security for iframe content
            allowed_domains=[
                # Standard domains
                "*",
                # Knipp Wolf iframe domains
                "*.knippwolf-netlease.com",
                "knippwolf-netlease.com",
                # Add other common iframe domains
                "*.marcusmillichap.com",
                "*.cegadvisors.com",
                "*.netlease.com",
                "*.duwestrealty.com",
                "*.levyretail.com",
                "*.theblueoxgroup.com",
                "*.apex-cre.com",
                "*.tag-industrial.com",
                "*.netleaseadvisorygroup.com",
                "*.valuenetlease.com"
            ]
        )
        
        # Configure browser session (remove invalid parameters)
        self.browser_session = BrowserSession(
            browser_profile=self.browser_profile,
            keep_alive=True
        )
        
        # Track downloads
        self.downloaded_files = []
        self.download_handlers_setup = False

    async def setup_download_handlers(self):
        """Set up download event handlers on the current page"""
        if self.download_handlers_setup:
            return
            
        try:
            page = await self.browser_session.get_current_page()
            
            # Set up download handler
            async def handle_download(download):
                try:
                    print(f"🎯 Download detected: {download.suggested_filename}")
                    
                    # Create filename
                    filename = download.suggested_filename or f"download_{int(time.time())}.pdf"
                    clean_filename = filename.replace("/", "-").replace("\\", "-")
                    download_path = self.downloads_dir / clean_filename
                    
                    # Save the download
                    await download.save_as(download_path)
                    self.downloaded_files.append(download_path)
                    
                    print(f"✅ Downloaded: {download_path}")
                    print(f"📄 File size: {download_path.stat().st_size // 1024} KB")
                    
                except Exception as e:
                    print(f"❌ Download handler error: {e}")
            
            # Attach the download handler
            page.on("download", handle_download)
            self.download_handlers_setup = True
            print("🔧 Download handlers set up successfully")
            
        except Exception as e:
            print(f"❌ Error setting up download handlers: {e}")

    
    async def monitor_downloads(self, agent):
        """Enhanced monitor with download handler setup"""
        try:
            # Set up download handlers if not already done
            await self.setup_download_handlers()
            
            page = await agent.browser_session.get_current_page()
            current_url = page.url
            
            # Log progress
            step_count = len(agent.state.history.model_actions()) if hasattr(agent, 'state') and agent.state else 0
            print(f"📍 Step {step_count}: {current_url}")
            
            # Check for download-related elements
            try:
                pdf_links = await page.locator('a[href*=".pdf"], a[href*="download"], [class*="download"]').count()
                if pdf_links > 0:
                    print(f"🎯 Found {pdf_links} potential download elements")
            except:
                pass
                
            # Report current downloads
            if self.downloaded_files:
                print(f"📊 Current downloads: {len(self.downloaded_files)}")
                
        except Exception as e:
            print(f"Monitor error: {e}")

    async def batch_download(self, urls: list) -> list:
        """Download OM/Flyers from multiple URLs"""
        results = []
        
        for i, url in enumerate(urls, 1):
            print(f"\n📊 Processing URL {i}/{len(urls)}")
            print("=" * 50)
            
            # Reset downloaded files for each URL
            self.downloaded_files = []
            
            # Create new browser session for each URL
            self.browser_session = BrowserSession(
                browser_profile=self.browser_profile
            )
            
            result = await self.download_om_flyer(url)
            results.append(result)
            
            # Wait between downloads to be respectful to servers
            if i < len(urls):
                print("⏸️ Waiting 15 seconds before next download...")
                await asyncio.sleep(15)
        
        return results

    async def download_om_flyer(self, url: str) -> dict:
        """
        Main workflow to download OM/Flyer from a given URL using a dynamic strategy
        """
        # Record start time
        start_time = time.time()
        
        result = {
            "success": False,
            "url": url,
            "downloaded_files": [],
            "error": None,
            "steps_completed": [],
            "execution_time_seconds": 0
        }
        
        try:
            print(f"🏠 Starting OM/Flyer download workflow for: {url}")
            print(f"📁 Downloads will be saved to: {self.downloads_dir}")
            
            # Set up download handlers before starting the agent
            await self.setup_download_handlers()
            
            # --- Scout Phase to Determine Page Type ---
            print("\n🔍 Scout Phase: Determining property count...")
            scout_agent = Agent(
                task=f"""Examine the page at {url} and count how many distinct property brochures or Offering Memorandums are available for download. Look for buttons or links like "Download Brochure", "Download OM", "View Details", "Marketing Package", etc., that lead to a download.
                
After scanning the page, provide ONLY a single number representing the count of properties. For example, if you find 3 distinct properties, your final response should be just "3". Do not add any other text.""",
                llm=self.llm,
                browser_session=self.browser_session,
                controller=controller
            )
            
            # Run scout for a few steps to classify the page
            await scout_agent.run(max_steps=5)

            # Extract the count from the last agent message
            property_count = 1  # Default to 1
            try:
                last_message = scout_agent.state.history.model_actions()[-1].text.strip()
                numbers = [int(s) for s in last_message.split() if s.isdigit()]
                if numbers:
                    property_count = numbers[0]
            except (IndexError, AttributeError, ValueError, TypeError):
                print("⚠️ Could not determine property count from scout, assuming single property.")
                property_count = 1
            
            if property_count == 0: # If it sees 0, it probably failed or there is actually one.
                property_count = 1

            print(f"🕵️ Scout identified {property_count} property/properties. Choosing strategy...")

            # --- Execution Phase: Choose Strategy Based on Count ---
            task_prompt = ""
            if property_count > 1:
                print("🤖 Strategy: TRUE BATCH APPROACH for multiple properties.")
                task_prompt = f'''You are already on the page {url}. Your task is to download ALL {property_count} property brochures using the TRUE BATCH APPROACH.

                ═══════════════════════════════════════════════════════════════════════════════════
                🚀 **TRUE BATCH APPROACH** (Efficient for multiple properties)
                ═══════════════════════════════════════════════════════════════════════════════════
                
                **PHASE 1: INTELLIGENT SCAN FOR OFFERING MEMORANDUM DOWNLOADS**
                ───────────────────────────────────────────────────────────────────────────────────
                1. **GOAL**: Find ALL buttons/links that lead to Offering Memorandums, marketing materials, or property documents
                
                2. **EXAMPLE KEYWORDS** (but not limited to these - use your intelligence):
                   - "Flyer", "Package", "OM", "Brochure", "Download", "View"
                   - "Marketing", "Investment", "Property", "Memorandum", "Summary", "Documents"
                   - Look for ANY words that suggest downloadable property marketing materials
                
                3. **SMART SCROLLING STRATEGY**:
                   - Start at current position and scan visible area for download-related buttons
                   - If NO relevant download buttons found in current view:
                     * If you're at/near the TOP: scroll DOWN using 'scroll_down' with `pages=0.5`
                     * If you're at/near the BOTTOM: scroll UP using 'scroll_up' with `pages=0.5`
                     * If you're in the MIDDLE: try scrolling DOWN first, then UP if needed
                   - **AVOID REPETITION**: Keep track of what you've already seen - don't analyze the same content multiple times
                   - Continue until you find ~{property_count} download buttons across the entire page
                
                4. Do NOT click any download buttons yet - just identify their locations
                5. Once found, return to TOP of page to begin clicking
                
                **PHASE 2: RAPID BUTTON CLICKING**
                ───────────────────────────────────────────────────────────────────────────────────
                1. Starting from the TOP, click ALL buttons that represent Offering Memorandums or property marketing materials
                2. Click buttons rapidly. Let PDF tabs accumulate in the background.
                3. Continue until you've clicked all ~{property_count} download buttons.
                4. **CRITICAL**: Do NOT click the same download button multiple times
                5. **IMPORTANT**: Many download buttons don't show visual changes - this is normal
                
                **PHASE 3: BATCH PDF PROCESSING**
                ───────────────────────────────────────────────────────────────────────────────────
                1. You should now have ~{property_count} PDF tabs open.
                2. Systematically process each PDF tab: Switch to tab → Call 'download_pdf_direct' → Close tab.
                3. Continue until all PDF tabs are processed and only the main page remains.
                4. **MANDATORY**: If 'download_pdf_direct' returns "DOWNLOAD COMPLETE!" message, immediately close that tab and move to next
                5. **NO REPEATS**: Never download the same file twice - if you see success, move on immediately
                
                **START**: Begin Phase 1 - intelligently scan for OM download buttons.
                '''
            else:
                print("🤖 Strategy: Standard approach for single property.")
                task_prompt = f'''Your task is to download the Offering Memorandum (OM) or marketing flyer from the current page ({url}).

                **STEP 1: INTELLIGENT SEARCH FOR OFFERING MEMORANDUM DOWNLOADS**
                ───────────────────────────────────────────────────────────────────────────────────
                1. **PRIMARY GOAL**: Find buttons/links that represent downloadable Offering Memorandums, marketing materials, or property documents
                
                2. **FLEXIBLE KEYWORD DETECTION** (examples, not exhaustive):
                   - Common terms: "Flyer", "Package", "OM", "Brochure", "Download", "View"
                   - Marketing terms: "Marketing Package", "Investment Package", "Property Summary"
                   - Document terms: "Offering Memorandum", "Investment Summary", "Property Details"
                   - Action terms: "Get Package", "Download Now", "View Details"
                   - **USE YOUR INTELLIGENCE**: Look for ANY text that suggests downloadable property marketing materials

                3. **INTELLIGENT SCROLLING STRATEGY**:
                   - **CURRENT SCAN**: First, thoroughly examine what's currently visible for OM-related downloads
                   - **SMART MOVEMENT**: If no relevant downloads found in current viewport:
                     * **If near TOP of page**: Use 'scroll_down' with `pages=0.5` to explore downward
                     * **If near BOTTOM of page**: Use 'scroll_up' with `pages=0.5` to explore upward  
                     * **If in MIDDLE**: Try scrolling down first, then up if needed
                   - **AVOID REPETITION**: Don't re-analyze the same content you've already examined
                   - **PERSISTENCE**: Keep exploring different page sections until you find download elements
                   - **FALLBACK**: Only if NO text-based downloads found after thorough search, look for download icons

                **STEP 2: DOWNLOAD EXECUTION**
                ───────────────────────────────────────────────────────────────────────────────────
                4. Once you find the appropriate download button, click it. This will either:
                   a) DIRECT DOWNLOAD: File downloads immediately to downloads folder, OR
                   b) NEW TAB PDF: PDF opens in a new tab that needs to be downloaded
                   c) IFRAME FORM: Form appears within an iframe (common on Knipp Wolf sites)
                
                FOR IFRAME FORMS (Knipp Wolf, Marcus & Millichap subdomain sites):
                   - If you suspect the page uses iframes for forms, call the 'handle_iframe_forms' action
                   - This will automatically detect iframes, fill forms, and click download buttons within them
                
                FOR REGULAR FORMS (if a form appears on main page):
                   - Fill it out with professional data:
                     * Name: John Doe
                     * Email: johndoe@email.com
                     * Phone: 555-123-4567
                     * Company: Real Estate Investments LLC
                     * Use 'select_dropdown_option_generic' for dropdowns
                     * Use 'check_terms_checkbox' for terms acceptance
                   - After filling ALL form fields, scroll to find Submit button if not visible
                   - Click Submit button (ignore CAPTCHA errors)
                   - IMMEDIATELY use 'done' action after clicking final download button
                
                FOR DIRECT PDF LINKS (if PDF opens in new tab):
                   - Switch to PDF tab and call 'download_pdf_direct' action
                   - IMMEDIATELY use 'done' action after download
                
                **CRITICAL RULES**:
                - Use intelligence to identify OM-related downloads, don't rely only on exact keyword matches
                - Avoid scanning the same page section repeatedly
                - Scroll systematically based on your current position
                - Once you click final download button, IMMEDIATELY use 'done' action
                - Do NOT click the same download button multiple times
                - Many download buttons don't show visual changes - this is normal
                - **MANDATORY**: If 'download_pdf_direct' returns "DOWNLOAD COMPLETE!" message, you MUST call 'done' immediately
                - **NO REPEATS**: Never download the same file twice - if you see success, stop immediately
                
                **START**: Begin by intelligently scanning current viewport for OM download opportunities.
                '''
            
            print("\n🤖 Main Agent: Executing selected strategy...")
            
            # Create agent with the selected task, reusing the browser session
            agent = Agent(
                task=task_prompt,
                llm=self.llm,
                browser_session=self.browser_session,
                controller=controller,
            )
            
            # Run the agent with a dynamic step limit
            max_steps = 50 if property_count > 1 else 18
            await agent.run(
                on_step_start=self.monitor_downloads,
                max_steps=max_steps
            )
            
            result["steps_completed"].append("Browser Use agent completed")
            
            # Wait for downloads to complete
            print("⏳ Waiting 5 seconds for downloads to complete...")
            await asyncio.sleep(5)
            
            # Check results
            if self.downloaded_files:
                result["success"] = True
                result["downloaded_files"] = [str(f) for f in self.downloaded_files]
                result["steps_completed"].append("Download verified")
                print(f"\n🎉 Success! Downloaded {len(self.downloaded_files)} file(s):")
                for file_path in self.downloaded_files:
                    file_path = Path(file_path)
                    print(f"  • {file_path.name} ({file_path.stat().st_size // 1024} KB)")
            else:
                # Also check for any PDF files that might have been downloaded via custom action
                pdf_files = list(self.downloads_dir.glob("*.pdf"))
                if pdf_files:
                    result["success"] = True
                    result["downloaded_files"] = [str(f) for f in pdf_files]
                    result["steps_completed"].append("Download verified via custom action")
                    print(f"\n🎉 Success! Downloaded {len(pdf_files)} file(s) via custom action:")
                    for file_path in pdf_files:
                        print(f"  • {file_path.name} ({file_path.stat().st_size // 1024} KB)")
                    self.downloaded_files = pdf_files
                else:
                    result["error"] = "No files were successfully downloaded"
                    print("❌ No files were successfully downloaded")
            
        except Exception as e:
            result["error"] = str(e)
            print(f"❌ Error during workflow: {e}")
        
        finally:
            end_time = time.time()
            result["execution_time_seconds"] = end_time - start_time
            
            print(f"\n⏱️ Workflow Execution Time: {result['execution_time_seconds']:.1f} seconds")
            
            try:
                await self.browser_session.close()
            except:
                pass
        
        return result

def print_results_summary(results: list):
    """Print a summary of download results"""
    print("\n" + "="*60)
    print("📊 DOWNLOAD SUMMARY")
    print("="*60)
    
    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]
    
    print(f"✅ Successful downloads: {len(successful)}")
    print(f"❌ Failed downloads: {len(failed)}")
    
    if successful:
        print("\n🎉 Successfully Downloaded:")
        for result in successful:
            if result["downloaded_files"]:
                for file_path in result["downloaded_files"]:
                    file_name = Path(file_path).name
                    print(f"  • {file_name} from {result['url']}")
    
    if failed:
        print("\n❌ Failed Downloads:")
        for result in failed:
            print(f"  • {result['url']}: {result['error']}")

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
        downloader = OMFlyerDownloader()
        
        print(f"🎬 Browser will be visible for GIF recording")
        print(f"📁 Downloads will be saved to: {downloader.downloads_dir}")
        
        if len(urls) == 1:
            result = await downloader.download_om_flyer(urls[0])
            print_results_summary([result])
        else:
            results = await downloader.batch_download(urls)
            print_results_summary(results)
            
    except Exception as e:
        print(f"❌ Error: {e}")
        if "OPENAI_API_KEY" in str(e):
            print("💡 Set your OpenAI API key: export OPENAI_API_KEY='your-key-here'")

if __name__ == "__main__":
    asyncio.run(main()) 