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

# Custom action to download PDF directly using aiohttp
@controller.action('Download PDF directly from URL')
async def download_pdf_direct(page: Page) -> ActionResult:
    """
    Download PDF directly from the current page URL using aiohttp
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
        if not filename.endswith('.pdf'):
            filename += '.pdf'
        
        # Clean filename
        clean_filename = filename.replace('%20', '-').replace(' ', '-')
        download_path = downloads_dir / clean_filename
        print(f"💾 Target file path: {download_path}")
        
        # Download using Playwright's browser context (maintains session/cookies)
        print("🌐 Starting download using browser context...")
        
        try:
            # Use the browser's request context to maintain session
            context = page.context
            response = await context.request.get(current_url)
            
            print(f"📊 Response status: {response.status}")
            print(f"📋 Response headers: {response.headers}")
            
            if response.status == 200:
                content = await response.body()
                content_length = len(content)
                print(f"📥 Downloaded {content_length} bytes")
                
                if content_length == 0:
                    return ActionResult(extracted_content="❌ Downloaded content is empty")
                
                # Check if it's HTML content (tracking/redirect page)
                content_start = content[:100].decode('utf-8', errors='ignore').lower()
                if '<html' in content_start or '<head' in content_start or '<script' in content_start:
                    print(f"⚠️ Got HTML instead of PDF - likely a tracking/redirect page")
                    print(f"🔄 Trying alternative download methods...")
                    
                    # Method 1: Try using browser's built-in download
                    try:
                        await page.keyboard.press('Control+s')  # Save page
                        await page.wait_for_timeout(3000)
                        
                        # Check if file was downloaded
                        potential_files = list(downloads_dir.glob("*.pdf"))
                        if potential_files:
                            latest_file = max(potential_files, key=lambda x: x.stat().st_mtime)
                            if latest_file.stat().st_size > 10000:  # Reasonable PDF size
                                file_size_kb = latest_file.stat().st_size // 1024
                                print(f"✅ File downloaded via browser save: {latest_file} ({file_size_kb} KB)")
                                return ActionResult(extracted_content=f"✅ Downloaded PDF: {latest_file.name} ({file_size_kb} KB) to {latest_file}")
                    except Exception as save_error:
                        print(f"⚠️ Browser save method failed: {save_error}")
                    
                    # Method 2: Look for direct PDF links in the HTML
                    try:
                        html_content = content.decode('utf-8', errors='ignore')
                        import re
                        
                        # Look for PDF URLs in the HTML
                        pdf_url_patterns = [
                            r'href=["\']([^"\']*\.pdf[^"\']*)["\']',
                            r'src=["\']([^"\']*\.pdf[^"\']*)["\']',
                            r'url\(["\']?([^"\']*\.pdf[^"\']*)["\']?\)',
                            r'location\.href\s*=\s*["\']([^"\']*\.pdf[^"\']*)["\']',
                        ]
                        
                        for pattern in pdf_url_patterns:
                            matches = re.findall(pattern, html_content, re.IGNORECASE)
                            for match in matches:
                                if match and match.endswith('.pdf'):
                                    print(f"🔗 Found potential PDF URL in HTML: {match}")
                                    
                                    # Make URL absolute if needed
                                    if match.startswith('http'):
                                        pdf_url = match
                                    else:
                                        from urllib.parse import urljoin
                                        pdf_url = urljoin(current_url, match)
                                    
                                    # Try downloading the direct PDF URL
                                    try:
                                        pdf_response = await context.request.get(pdf_url)
                                        if pdf_response.status == 200:
                                            pdf_content = await pdf_response.body()
                                            if pdf_content.startswith(b'%PDF'):
                                                # Save the PDF
                                                pdf_filename = pdf_url.split('/')[-1]
                                                clean_pdf_filename = pdf_filename.replace('%20', '-').replace(' ', '-')
                                                pdf_download_path = downloads_dir / clean_pdf_filename
                                                
                                                with open(pdf_download_path, 'wb') as f:
                                                    f.write(pdf_content)
                                                
                                                file_size_kb = len(pdf_content) // 1024
                                                print(f"✅ Downloaded PDF from extracted URL: {pdf_download_path} ({file_size_kb} KB)")
                                                return ActionResult(extracted_content=f"✅ Downloaded PDF: {clean_pdf_filename} ({file_size_kb} KB) to {pdf_download_path}")
                                    except Exception as direct_error:
                                        print(f"⚠️ Failed to download from extracted URL {pdf_url}: {direct_error}")
                                        continue
                    except Exception as html_parse_error:
                        print(f"⚠️ Failed to parse HTML for PDF URLs: {html_parse_error}")
                    
                    return ActionResult(extracted_content="❌ Got HTML redirect page instead of PDF - could not find direct PDF URL")
                
                # Verify it's actually PDF content
                if not content.startswith(b'%PDF'):
                    print(f"⚠️ Content doesn't start with PDF header. First 50 bytes: {content[:50]}")
                    return ActionResult(extracted_content="❌ Downloaded content is not a valid PDF")
                
                # Save the PDF
                print(f"💾 Writing {content_length} bytes to: {download_path}")
                with open(download_path, 'wb') as f:
                    f.write(content)
                
                # Verify file was written
                if download_path.exists():
                    file_size_kb = download_path.stat().st_size // 1024
                    print(f"✅ File successfully saved: {download_path} ({file_size_kb} KB)")
                    return ActionResult(extracted_content=f"✅ Downloaded PDF: {clean_filename} ({file_size_kb} KB) to {download_path}")
                else:
                    return ActionResult(extracted_content=f"❌ File was not created at: {download_path}")
            else:
                error_text = await response.text()
                print(f"❌ HTTP Error {response.status}: {error_text[:200]}")
                return ActionResult(extracted_content=f"❌ Failed to download PDF. HTTP status: {response.status}")
                
        except Exception as request_error:
            print(f"❌ Browser request failed: {request_error}")
            # Fallback to direct browser navigation method
            try:
                print("🔄 Trying fallback: direct browser download...")
                await page.goto(current_url)
                await page.wait_for_load_state('networkidle')
                
                # Try to trigger browser's built-in download
                await page.keyboard.press('Control+s')  # Save page
                await page.wait_for_timeout(3000)
                
                # Check if file was downloaded
                if download_path.exists():
                    file_size_kb = download_path.stat().st_size // 1024
                    print(f"✅ File downloaded via browser: {download_path} ({file_size_kb} KB)")
                    return ActionResult(extracted_content=f"✅ Downloaded PDF: {clean_filename} ({file_size_kb} KB) to {download_path}")
                else:
                    return ActionResult(extracted_content="❌ Browser download fallback failed")
                    
            except Exception as fallback_error:
                print(f"❌ Fallback method also failed: {fallback_error}")
                return ActionResult(extracted_content=f"❌ All download methods failed: {str(fallback_error)}")

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

    async def download_om_flyer(self, url: str) -> dict:
        """
        Main workflow to download OM/Flyer from a given URL using both methods
        """
        result = {
            "success": False,
            "url": url,
            "downloaded_files": [],
            "error": None,
            "steps_completed": []
        }
        
        try:
            print(f"🏠 Starting OM/Flyer download workflow for: {url}")
            print(f"📁 Downloads will be saved to: {self.downloads_dir}")
            
            # Set up download handlers before starting the agent
            await self.setup_download_handlers()
            
            # Method 1: Try Browser Use Agent first
            print("\n🤖 Method 1: Using Browser Use Agent...")
            
            # Create agent with download-focused task
            agent = Agent(
                task=f"""Navigate to {url} and download PDF files by:
                1. Look for download buttons or links like "VIEW PACKAGE", "Download Brochure", "Offering Memorandum", etc.
                2. If no text-based download buttons are found, look for DOWNLOAD ICONS such as:
                   - Downward arrow symbols (↓, ⬇, ▼)
                   - Download icons (usually arrow pointing down)
                   - Document icons with download indicators
                   - Any clickable icons that typically represent downloads
                3. **CRITICAL SCROLLING RULE**: If you don't immediately see download buttons/links on the current viewport:
                   - ALWAYS use 'scroll_down' action with `pages=0.5` to scroll down half a page
                   - Keep scrolling until you find download elements
                   - Do NOT get stuck analyzing the same elements repeatedly
                   - If you see the same elements for 2+ consecutive steps, SCROLL DOWN
                4. Clicking the download button. This will either:
                   a) DIRECT DOWNLOAD: File downloads immediately to downloads folder, OR
                   b) NEW TAB PDF: PDF opens in a new tab that needs to be downloaded
                   c) IFRAME FORM: Form appears within an iframe (common on Knipp Wolf sites)
                
                FOR IFRAME FORMS (Knipp Wolf, Marcus & Millichap subdomain sites):
                   - If you suspect the page uses iframes for forms, call the 'handle_iframe_forms' action
                   - This will automatically detect iframes, fill forms, and click download buttons within them
                   - Common iframe sites: *.knippwolf-netlease.com, subdomain.marcusmillichap.com
                
                FOR REGULAR FORMS (if a form appears on main page):
                   - Fill it out with professional data:
                     * Name: John Doe
                     * Email: anish@theus.ai (for any login/signup)
                     * Password: Gillellaanish@123 (for any login/signup)
                     * Phone: 555-123-4567
                     * Company: Real Estate Investments LLC
                     * WHEN YOU ENCOUNTER A DROPDOWN: Call the 'select_dropdown_option_generic' action with parameters:
                       - dropdown_identifier="Contact Type" and option_to_select="Broker" (for contact type)
                       - dropdown_identifier="State" and option_to_select="California" (for state dropdowns)
                       - dropdown_identifier="City" and option_to_select="Los Angeles" (for city dropdowns)
                     * WHEN YOU NEED TO ACCEPT TERMS: Call the 'check_terms_checkbox' action (no parameters needed)
                   - After filling ALL form fields, find and click the FORM SUBMIT button (typically labeled "Submit", "Send", "Get Download", "Download Now", or "Send Request").
                   - If the submit button is NOT visible after filling the form, use 'scroll_down' action with `pages=0.5` to scroll and find it.
                   - After successfully submitting the form, click the NEW download button that appears.
                   - IMMEDIATELY after clicking the final download button, use the 'done' action - DO NOT wait or check for confirmations.
                
                FOR SITES WITH COMPLEX/JAVASCRIPT-HEAVY ELEMENTS:
                   - If normal clicking fails but you can see download elements, use the 'force_click_download_element' action
                   - This handles sites where elements are visually present but not properly indexed
                
                FOR DIRECT PDF LINKS (if PDF opens in new tab):
                   - If a PDF opens directly in a new tab, switch to that tab and call 'download_pdf_direct' action.
                   - IMMEDIATELY after the download action, use the 'done' action.
                
                ANTI-LOOP RULE: If you find yourself evaluating the same page content for 3+ consecutive steps without taking action, immediately scroll down or try a different approach.
                
                CRITICAL: Once you click any final download button (like "Download Marketing Package", "Download PDF", etc.), IMMEDIATELY use the 'done' action. DO NOT wait, DO NOT check for confirmations, DO NOT click multiple times.
                
                COMPLETION CRITERIA: Task is complete immediately after clicking the final download button.""",
                llm=self.llm,
                browser_session=self.browser_session,
                controller=controller
            )
            
            # Run the agent with an increased step limit to allow for careful scrolling and form filling
            await agent.run(
                on_step_start=self.monitor_downloads,
                max_steps=18 # Increased limit for form filling, submission, and download
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
                    # Make sure to handle Path objects correctly
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
                    # Update the tracked files list
                    self.downloaded_files = pdf_files
                else:
                    result["error"] = "No files were successfully downloaded"
                    print("❌ No files were successfully downloaded")
            
        except Exception as e:
            result["error"] = str(e)
            print(f"❌ Error during workflow: {e}")
        
        finally:
            # Close browser session
            try:
                await self.browser_session.close()
            except:
                pass
        
        return result

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