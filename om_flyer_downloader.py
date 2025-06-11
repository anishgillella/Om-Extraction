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

# Load environment variables
load_dotenv()

# Create controller for custom actions
controller = Controller()

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
    """Handle iframe forms for contact forms and downloads"""
    try:
        # First check if there are any iframes
        iframe_count = await page.locator('iframe').count()
        print(f"🔍 Found {iframe_count} iframe(s) on page")
        
        if iframe_count == 0:
            return ActionResult(extracted_content="No iframes found on the page")
        
        # Get all iframes
        iframes = await page.locator('iframe').all()
        
        for i, iframe_element in enumerate(iframes):
            try:
                print(f"🔍 Processing iframe {i+1}/{len(iframes)}")
                
                # Get iframe src
                src = await iframe_element.get_attribute('src')
                print(f"📄 Iframe src: {src}")
                
                # Get frame
                frame = await iframe_element.content_frame()
                if not frame:
                    print(f"❌ Could not access iframe {i+1} content")
                    continue
                
                # Wait for frame to load
                await frame.wait_for_load_state('networkidle', timeout=10000)
                
                # Check if it's a contact form
                form_count = await frame.locator('form').count()
                print(f"📝 Found {form_count} form(s) in iframe {i+1}")
                
                if form_count > 0:
                    print(f"✅ Found contact form in iframe {i+1}, filling it out")
                    result = await fill_iframe_form(frame)
                    if "filled successfully" in result:
                        return ActionResult(extracted_content=f"✅ Successfully filled contact form in iframe {i+1}. {result}")
                
                # Check for download buttons in iframe
                download_buttons = await frame.locator('a[href*=".pdf"], [class*="download"], [text*="download" i], [text*="Download" i]').count()
                if download_buttons > 0:
                    print(f"🎯 Found {download_buttons} potential download button(s) in iframe {i+1}")
                    
                    # Try to click the first download button
                    button = frame.locator('a[href*=".pdf"], [class*="download"], [text*="download" i], [text*="Download" i]').first
                    button_text = await button.text_content() if await button.count() > 0 else "Download Button"
                    
                    if await button.count() > 0:
                        print(f"🖱️ Clicking download button: {button_text}")
                        await button.click()
                        return ActionResult(extracted_content=f"✅ Clicked download button '{button_text}' in iframe {i+1}")
                
            except Exception as iframe_error:
                print(f"❌ Error processing iframe {i+1}: {iframe_error}")
                continue
        
        return ActionResult(extracted_content=f"Processed {len(iframes)} iframe(s), no actionable forms or downloads found")
        
    except Exception as e:
        return ActionResult(extracted_content=f"❌ Error handling iframes: {e}")

@controller.action('Stop workflow immediately after download')
async def stop_workflow_after_download(page: Page) -> ActionResult:
    """Custom action to stop the workflow after successful download"""
    return ActionResult(
        extracted_content="✅ WORKFLOW STOPPED - Download completed successfully. Task finished.",
        include_in_memory=True
    )

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
            
            scout_agent = Agent(
                task=scout_prompt,
                llm=self.llm,
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
            import re
            
            # First try to find a standalone number at the end of result
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

class OMFlyerDownloader:
    def __init__(self, openai_api_key=None):
        """Initialize the OM/Flyer downloader with enhanced configuration"""
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        if not self.openai_api_key:
            raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY environment variable.")
        
        # Initialize LLM with enhanced configuration for better task understanding
        self.llm = ChatOpenAI(
            api_key=self.openai_api_key,
            model="gpt-4o",  # Most capable model for complex tasks
            temperature=0.1,  # Low temperature for more consistent behavior
        )
        
        # Set up browser profile for improved navigation
        self.browser_profile = BrowserProfile(
            download_dir=str(Path.home() / "Downloads"),
            # Allowing all domains since we need to navigate to various property sites
            allowed_domains=["*"],
            cookies_file=None,
            storage_state=None,
            headless=False,  # Visible for debugging and GIF recording
            browser_type="chromium",
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

    def get_domain_folder(self, url: str) -> Path:
        """Get domain-specific folder for organizing downloads"""
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.replace('www.', '').replace('.com', '').replace('.net', '').replace('.org', '')
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
        """Enhanced monitor with multiple stop mechanisms"""
        try:
            # Set up download handlers if not already done
            await self.setup_download_handlers()
            
            page = await agent.browser_session.get_current_page()
            current_url = page.url
            
            # Log progress
            step_count = len(agent.state.history.model_actions()) if hasattr(agent, 'state') and agent.state else 0
            print(f"📍 Step {step_count}: {current_url}")
            
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
        Main workflow with 2-agent architecture: Scout first, then Main agent based on count
        """
        # Record start time
        start_time = time.time()
        
        # Store current URL for domain extraction in download handlers
        self.current_url = url
        
        result = {
            "success": False,
            "url": url,
            "downloaded_files": [],
            "error": None,
            "steps_completed": [],
            "execution_time_seconds": 0,
            "om_buttons_found": 0,
            "strategy_used": ""
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
            if om_button_count == 0:
                print("\n❌ PHASE 2: No OM buttons found - Skipping main agent")
                result["strategy_used"] = "skip"
                result["error"] = "No OM buttons found on the webpage"
                result["steps_completed"].append("Skipped main agent - no buttons found")
                return result
                
            elif om_button_count == 1:
                print("\n🤖 PHASE 2: Single OM button - Using focused download strategy")
                result["strategy_used"] = "single"
                await self._download_single_om(url, result)
                
            else:  # om_button_count > 1
                print(f"\n🤖 PHASE 2: Multiple OM buttons ({om_button_count}) - Using batch download strategy")
                result["strategy_used"] = "batch"
                await self._download_multiple_oms(url, result, om_button_count)
            
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
            result["error"] = str(e)
            print(f"❌ Error during workflow: {e}")
        
        finally:
            end_time = time.time()
            result["execution_time_seconds"] = end_time - start_time
            
            print(f"\n⏱️ Workflow Execution Time: {result['execution_time_seconds']:.1f} seconds")
            print(f"📊 Strategy Used: {result['strategy_used']} ({result['om_buttons_found']} buttons)")
            
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
            
            task_prompt = f'''Your task is to download the SINGLE Offering Memorandum (OM) from: {url}

            **CONTEXT**: Scout agent confirmed there is exactly 1 OM button on this page.

            **STEP 1: NAVIGATE AND LOCATE**
            ───────────────────────────────────────────────────────────────────────────────────
            1. Navigate to: {url}
            2. **FIND THE OM BUTTON**: Look for the single download button (VIEW PACKAGE, Download Brochure, etc.)
            3. Use half-page scrolling (`pages=0.5`) if needed to locate it

            **STEP 2: DOWNLOAD EXECUTION - STOP IMMEDIATELY AFTER**
                ───────────────────────────────────────────────────────────────────────────────────
            1. Click the OM button
            2. **IF FORM APPEARS**: Fill with John Doe, johndoe@email.com, 555-123-4567 and submit
            3. **IF PDF OPENS IN NEW TAB**: Use 'download_pdf_direct' action to download it
            4. **IF DIRECT DOWNLOAD**: File will download automatically
            5. **IMMEDIATELY call 'done' after ANY download action**
                
                **CRITICAL RULES**:
            - After clicking download/submit button, IMMEDIATELY call 'done'
            - If PDF opens in new tab and you can't switch tabs, use 'download_pdf_direct'
            - Do not continue working after any download action
            
            START: Find and click the single OM button, handle the download, then stop immediately.'''
            
            # Create main agent
            agent = Agent(
                task=task_prompt,
                llm=self.llm,
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

    async def _download_multiple_oms(self, url: str, result: dict, expected_count: int):
        """Handle multiple OM buttons download (batch approach)"""
        try:
            # Set up download handlers before starting the agent
            await self.setup_download_handlers()
            
            task_prompt = f'''Your task is to download ALL {expected_count} Offering Memorandums from: {url}

            **CONTEXT**: Scout agent found {expected_count} OM buttons on this page.

            **STEP 1: NAVIGATE AND SCAN**
            ───────────────────────────────────────────────────────────────────────────────────
            1. Navigate to: {url}
            2. **SYSTEMATICALLY FIND ALL OM BUTTONS**: Use half-page scrolling to explore entire page
            3. Look for ALL buttons like: VIEW PACKAGE, Download Brochure, Download OM, etc.
            4. **COUNT THEM**: Confirm you found {expected_count} OM buttons

            **STEP 2: BATCH DOWNLOAD STRATEGY**
            ───────────────────────────────────────────────────────────────────────────────────
            1. **DOWNLOAD EACH OM SEQUENTIALLY**:
               - Click first OM button → handle form if needed → wait for download
               - Click second OM button → handle form if needed → wait for download  
               - Continue until all {expected_count} OMs are downloaded
            
            2. **FOR EACH DOWNLOAD**:
               - Fill forms with: John Doe, johndoe@email.com, 555-123-4567
               - Wait 2-3 seconds between downloads
               - Use 'download_pdf_direct' if PDFs open in new tabs
            
            3. **COMPLETION**: After downloading ALL {expected_count} OMs, call 'done'

            **CRITICAL RULES**:
            - Download ALL {expected_count} OMs before calling 'done'
            - Handle each download completely before moving to next
            - Do not stop after first download - continue until all are downloaded
            
            START: Find all {expected_count} OM buttons and download each one systematically.'''
            
            # Create main agent with more steps for batch processing
            agent = Agent(
                task=task_prompt,
                llm=self.llm,
                browser_session=self.browser_session,
                controller=controller,
            )
            
            # Use custom monitor that doesn't stop immediately for batch downloads
            async def batch_monitor(agent):
                """Monitor that allows multiple downloads before stopping"""
                try:
                    await self.setup_download_handlers()
                    
                    page = await agent.browser_session.get_current_page()
                    current_url = page.url
                    
                    step_count = len(agent.state.history.model_actions()) if hasattr(agent, 'state') and agent.state else 0
                    print(f"📍 Batch Step {step_count}: {current_url}")
                    
                    # Only stop when we have expected number of downloads
                    if len(self.downloaded_files) >= expected_count:
                        print(f"🛑 Batch complete! Downloaded {len(self.downloaded_files)}/{expected_count} files")
                        self.should_stop = True
                        raise StopIteration(f"Batch download completed - {len(self.downloaded_files)} files downloaded")
                        
                except StopIteration:
                    raise
                except Exception as e:
                    print(f"Batch monitor error: {e}")
            
            # Run the agent
            try:
                await agent.run(
                    on_step_start=batch_monitor,
                    max_steps=20  # More steps for multiple downloads
                )
            except StopIteration as e:
                print(f"🛑 Batch agent stopped: {e}")
                result["steps_completed"].append("Batch agent stopped after downloads completed")
            except Exception as e:
                if "StopIteration" in str(e):
                    print(f"🛑 Batch agent stopped: {e}")
                    result["steps_completed"].append("Batch agent stopped after downloads completed")
                else:
                    print(f"❌ Batch agent error: {e}")
                    raise e
            
            result["steps_completed"].append(f"Batch OM download completed - {len(self.downloaded_files)} files")
            
            # Wait for all downloads to complete
            print("⏳ Waiting 8 seconds for all batch downloads to complete...")
            await asyncio.sleep(8)
            
        except Exception as e:
            print(f"❌ Error in batch OM download: {e}")
            result["error"] = str(e)

def print_results_summary(results: list):
    """Print a summary of download results with 2-agent architecture details"""
    print("\n" + "="*70)
    print("📊 2-AGENT DOWNLOAD SUMMARY")
    print("="*70)
    
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
                print(f"\n  📄 {result['url']} [{strategy.upper()} - {button_count} button(s)]")
                for file_path in result["downloaded_files"]:
                    file_name = Path(file_path).name
                    print(f"    • {file_name}")
    
    if skipped:
        print("\n⏭️ Skipped (No OM Buttons Found):")
        for result in skipped:
            print(f"  • {result['url']}")
    
    if failed:
        print("\n❌ Failed Downloads:")
        for result in failed:
            strategy = result.get("strategy_used", "unknown")
            button_count = result.get("om_buttons_found", "?")
            print(f"  • {result['url']} [{strategy.upper()} - {button_count} button(s)]: {result['error']}")
    
    # Show efficiency stats
    total_time = sum(r["execution_time_seconds"] for r in results)
    total_files = sum(len(r["downloaded_files"]) for r in successful)
    
    print(f"\n⚡ Efficiency Stats:")
    print(f"  ⏱️  Total execution time: {total_time:.1f} seconds")
    print(f"  📁 Total files downloaded: {total_files}")
    if total_files > 0:
        print(f"  📊 Average time per file: {total_time/total_files:.1f} seconds")

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