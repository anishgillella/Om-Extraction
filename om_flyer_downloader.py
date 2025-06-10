#!/usr/bin/env python3
"""
OM/Flyer Downloader using Browser Use
Downloads Offering Memorandums and Flyers from real estate property pages
With comprehensive token tracking and cost analysis
"""

import asyncio
import os
import time
import aiohttp
from pathlib import Path
from browser_use import Agent, BrowserSession, BrowserProfile, Controller, ActionResult
from playwright.async_api import Page
from langchain_openai import ChatOpenAI
from langchain.callbacks.base import BaseCallbackHandler
from langchain.schema import LLMResult
from dotenv import load_dotenv
from urllib.parse import urlparse

# Load environment variables
load_dotenv()

# GPT-4o Pricing (as of current rates - November 2024)
GPT4O_PRICING = {
    "input_tokens_per_1k": 0.005,      # $5.00 per 1M tokens = $0.005 per 1K input tokens
    "cached_input_tokens_per_1k": 0.0025,  # $2.50 per 1M tokens = $0.0025 per 1K cached input tokens  
    "output_tokens_per_1k": 0.02,      # $20.00 per 1M tokens = $0.02 per 1K output tokens
}

class TokenTrackingCallback(BaseCallbackHandler):
    """Custom callback handler to track token usage and costs"""
    
    def __init__(self):
        self.total_tokens = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_cost = 0.0
        self.call_count = 0
        self.calls_history = []
    
    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        """Called when LLM ends running"""
        self.call_count += 1
        
        # Extract token usage from response
        if hasattr(response, 'llm_output') and response.llm_output:
            token_usage = response.llm_output.get('token_usage', {})
            if token_usage:
                prompt_tokens = token_usage.get('prompt_tokens', 0)
                completion_tokens = token_usage.get('completion_tokens', 0)
                total_tokens = token_usage.get('total_tokens', 0)
                
                # Update totals
                self.input_tokens += prompt_tokens
                self.output_tokens += completion_tokens
                self.total_tokens += total_tokens
                
                # Calculate cost for this call
                input_cost = (prompt_tokens / 1000) * GPT4O_PRICING["input_tokens_per_1k"]
                output_cost = (completion_tokens / 1000) * GPT4O_PRICING["output_tokens_per_1k"]
                call_cost = input_cost + output_cost
                self.total_cost += call_cost
                
                # Record this call
                call_info = {
                    "call_number": self.call_count,
                    "input_tokens": prompt_tokens,
                    "output_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "cost": call_cost,
                    "timestamp": time.time()
                }
                self.calls_history.append(call_info)
                
                print(f"💰 LLM Call #{self.call_count}: {prompt_tokens} input + {completion_tokens} output = {total_tokens} tokens (${call_cost:.4f})")
    
    def get_summary(self) -> dict:
        """Get comprehensive token usage and cost summary"""
        return {
            "total_calls": self.call_count,
            "total_tokens": self.total_tokens,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_cost_usd": self.total_cost,
            "average_tokens_per_call": self.total_tokens / max(1, self.call_count),
            "average_cost_per_call": self.total_cost / max(1, self.call_count),
            "calls_history": self.calls_history
        }
    
    def print_detailed_summary(self):
        """Print detailed cost and token analysis"""
        print("\n" + "="*60)
        print("💰 TOKEN USAGE & COST ANALYSIS")
        print("="*60)
        print(f"🤖 Model: GPT-4o")
        print(f"📞 Total LLM Calls: {self.call_count}")
        print(f"🔢 Total Tokens: {self.total_tokens:,}")
        print(f"  📥 Input Tokens: {self.input_tokens:,}")
        print(f"  📤 Output Tokens: {self.output_tokens:,}")
        print(f"💵 Total Cost: ${self.total_cost:.4f}")
        
        if self.call_count > 0:
            print(f"📊 Average per Call:")
            print(f"  🔢 Tokens: {self.total_tokens / self.call_count:.1f}")
            print(f"  💵 Cost: ${self.total_cost / self.call_count:.4f}")
        
        # Cost breakdown with updated pricing
        input_cost = (self.input_tokens / 1000) * GPT4O_PRICING["input_tokens_per_1k"]
        output_cost = (self.output_tokens / 1000) * GPT4O_PRICING["output_tokens_per_1k"]
        print(f"💸 Cost Breakdown:")
        print(f"  📥 Input: ${input_cost:.4f} ({self.input_tokens:,} tokens × ${GPT4O_PRICING['input_tokens_per_1k']}/1k)")
        print(f"  📤 Output: ${output_cost:.4f} ({self.output_tokens:,} tokens × ${GPT4O_PRICING['output_tokens_per_1k']}/1k)")
        print(f"  💡 Note: Cached input tokens are ${GPT4O_PRICING['cached_input_tokens_per_1k']}/1k (50% discount)")
        
        # Show most expensive calls
        if len(self.calls_history) > 0:
            print(f"\n🔝 Most Expensive Calls:")
            sorted_calls = sorted(self.calls_history, key=lambda x: x['cost'], reverse=True)
            for i, call in enumerate(sorted_calls[:3], 1):
                print(f"  {i}. Call #{call['call_number']}: {call['total_tokens']} tokens, ${call['cost']:.4f}")
        
        print("="*60)

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
        
        # Check if we've already downloaded this URL
        if hasattr(page, '_downloader_instance'):
            downloader = getattr(page, '_downloader_instance')
            if current_url in downloader.downloaded_urls:
                print(f"⏭️ Skipping duplicate download: {current_url}")
                return ActionResult(extracted_content=f"⏭️ Already downloaded: {current_url}")
        
        # More flexible PDF detection - check URL or content type
        is_pdf_url = (current_url.endswith('.pdf') or 
                     'pdf' in current_url.lower() or
                     '/uploads/' in current_url)
        
        if not is_pdf_url:
            print(f"❌ URL doesn't appear to be a PDF: {current_url}")
            return ActionResult(extracted_content=f"❌ Current page URL doesn't appear to be a PDF: {current_url}")
        
        # Get downloads directory from the browser session context
        # We'll store it in the page context for access
        downloads_dir = getattr(page, '_downloads_dir', None)
        
        # If no domain directory is set, derive it from the current URL
        if downloads_dir is None:
            # Extract domain from current URL for domain-specific folder
            from urllib.parse import urlparse
            parsed = urlparse(current_url)
            domain = parsed.netloc.lower()
            
            # Remove www. prefix if present
            if domain.startswith('www.'):
                domain = domain[4:]
            
            # Remove common TLD extensions for cleaner folder names
            domain_parts = domain.split('.')
            if len(domain_parts) >= 2:
                # Keep just the main domain name (e.g., "crossroadventures" from "crossroadventures.net")
                domain = domain_parts[0]
            
            # Clean domain name for use as folder name
            domain = domain.replace('-', '_').replace('.', '_')
            
            # Set up domain-specific downloads directory
            base_downloads_dir = Path("/Users/anishgillella/Desktop/Stuff/Theus/TheusAI/downloads")
            downloads_dir = base_downloads_dir / domain
            downloads_dir.mkdir(exist_ok=True, parents=True)
            print(f"🔧 Auto-created domain-specific directory from URL: {downloads_dir}")
        
        # Always use the domain-specific downloads directory
        downloads_dir.mkdir(exist_ok=True, parents=True)
        print(f"📁 Downloads directory: {downloads_dir}")
        
        # Show current downloads count
        existing_pdfs = list(downloads_dir.glob("*.pdf"))
        print(f"📊 Current PDFs in folder: {len(existing_pdfs)}")
        if existing_pdfs:
            print("📄 Existing files:")
            for pdf in existing_pdfs[-5:]:  # Show last 5 files
                print(f"  • {pdf.name}")
        
        # Extract filename from URL
        filename = current_url.split('/')[-1]
        if not filename.endswith('.pdf'):
            filename += '.pdf'
        
        # Clean filename
        clean_filename = filename.replace('%20', '-').replace(' ', '-')
        download_path = downloads_dir / clean_filename
        
        # Check if file already exists
        if download_path.exists():
            file_size_kb = download_path.stat().st_size // 1024
            print(f"📄 File already exists: {clean_filename} ({file_size_kb} KB)")
            if hasattr(page, '_downloader_instance'):
                downloader = getattr(page, '_downloader_instance')
                downloader.downloaded_urls.add(current_url)
                downloader.downloaded_filenames.add(clean_filename)
            return ActionResult(extracted_content=f"📄 File already exists: {clean_filename} ({file_size_kb} KB)")
        
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
                
                # Verify file was written and track the download
                if download_path.exists():
                    file_size_kb = download_path.stat().st_size // 1024
                    print(f"✅ File successfully saved: {download_path} ({file_size_kb} KB)")
                    
                    # Track this download to avoid duplicates
                    if hasattr(page, '_downloader_instance'):
                        downloader = getattr(page, '_downloader_instance')
                        downloader.downloaded_urls.add(current_url)
                        downloader.downloaded_filenames.add(clean_filename)
                        downloader.downloaded_files.append(download_path)
                        print(f"📊 Total unique downloads: {len(downloader.downloaded_urls)}")
                    
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
        
        # Set up base downloads directory
        self.base_downloads_dir = Path("/Users/anishgillella/Desktop/Stuff/Theus/TheusAI/downloads")
        self.base_downloads_dir.mkdir(exist_ok=True, parents=True)
        
        # Initialize token tracking
        self.token_tracker = TokenTrackingCallback()
        
        # Initialize LLM with token tracking callback
        self.llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0.0,
            api_key=self.api_key,
            callbacks=[self.token_tracker]  # Add token tracking callback
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
        self.downloaded_urls = set()  # Track URLs to avoid duplicates
        self.downloaded_filenames = set()  # Track filenames to avoid duplicates
        self.property_addresses = set()  # Track property addresses already processed

    def get_domain_folder(self, url: str) -> str:
        """Extract domain name from URL for creating subdirectories"""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # Remove www. prefix if present
        if domain.startswith('www.'):
            domain = domain[4:]
        
        # Remove common TLD extensions for cleaner folder names
        domain_parts = domain.split('.')
        if len(domain_parts) >= 2:
            # Keep just the main domain name (e.g., "crossroadventures" from "crossroadventures.net")
            domain = domain_parts[0]
        
        # Clean domain name for use as folder name
        domain = domain.replace('-', '_').replace('.', '_')
        
        return domain

    def setup_domain_downloads_dir(self, url: str) -> Path:
        """Set up domain-specific downloads directory"""
        domain_folder = self.get_domain_folder(url)
        self.downloads_dir = self.base_downloads_dir / domain_folder
        self.downloads_dir.mkdir(exist_ok=True, parents=True)
        
        print(f"📁 Domain-specific downloads directory: {self.downloads_dir}")
        return self.downloads_dir

    async def setup_download_handlers(self):
        """Set up download event handlers on the current page"""
        if self.download_handlers_setup:
            print(f"🔧 Download handlers already set up for: {self.downloads_dir}")
            return
            
        try:
            page = await self.browser_session.get_current_page()
            
            # Ensure downloads_dir is properly set
            if not hasattr(self, 'downloads_dir') or self.downloads_dir is None:
                print("⚠️ Downloads directory not set, using base directory as fallback")
                self.downloads_dir = self.base_downloads_dir
            
            # Store the downloads directory in the page context for access by download_pdf_direct
            setattr(page, '_downloads_dir', self.downloads_dir)
            # Store the downloader instance for tracking downloads
            setattr(page, '_downloader_instance', self)
            
            print(f"🔧 Setting up download handlers with directory: {self.downloads_dir}")
            
            # Set up download handler
            async def handle_download(download):
                try:
                    print(f"🎯 Download detected: {download.suggested_filename}")
                    
                    # Create filename
                    filename = download.suggested_filename or f"download_{int(time.time())}.pdf"
                    clean_filename = filename.replace("/", "-").replace("\\", "-")
                    
                    # Use the domain-specific downloads directory
                    download_path = self.downloads_dir / clean_filename
                    
                    # Check if we already have this file
                    if clean_filename in self.downloaded_filenames:
                        print(f"⏭️ Skipping duplicate download: {clean_filename}")
                        return
                    
                    # Save the download
                    await download.save_as(download_path)
                    self.downloaded_files.append(download_path)
                    self.downloaded_filenames.add(clean_filename)
                    
                    file_size_kb = download_path.stat().st_size // 1024
                    print(f"✅ Downloaded: {clean_filename}")
                    print(f"📄 File size: {file_size_kb} KB")
                    print(f"📁 Saved to: {download_path}")
                    print(f"📊 Total downloads so far: {len(self.downloaded_files)}")
                    
                except Exception as e:
                    print(f"❌ Download handler error: {e}")
            
            # Attach the download handler
            page.on("download", handle_download)
            self.download_handlers_setup = True
            print(f"✅ Download handlers set up successfully for: {self.downloads_dir}")
            
        except Exception as e:
            print(f"❌ Error setting up download handlers: {e}")
            import traceback
            print(f"📍 Traceback: {traceback.format_exc()}")

    async def download_om_flyer(self, url: str) -> dict:
        """
        Main workflow to download OM/Flyer from a given URL using both methods
        """
        # Record start time and token state
        start_time = time.time()
        start_tokens = self.token_tracker.total_tokens
        start_cost = self.token_tracker.total_cost
        
        result = {
            "success": False,
            "url": url,
            "downloaded_files": [],
            "error": None,
            "steps_completed": [],
            "token_usage": {
                "total_tokens": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
                "llm_calls": 0
            },
            "execution_time_seconds": 0
        }
        
        try:
            print(f"🏠 Starting OM/Flyer download workflow for: {url}")
            print(f"💰 Starting token count: {start_tokens:,} tokens, ${start_cost:.4f}")
            
            # Set up domain-specific downloads directory
            self.setup_domain_downloads_dir(url)
            print(f"📁 Downloads will be saved to: {self.downloads_dir}")
            
            # Set up download handlers before starting the agent
            await self.setup_download_handlers()
            
            # Method 1: Try Browser Use Agent first
            print("\n🤖 Method 1: Using Browser Use Agent...")
            
            # Create agent with download-focused task
            agent = Agent(
                task=f"""Navigate to {url} and download ALL property brochures using TRUE BATCH APPROACH:

                ═══════════════════════════════════════════════════════════════════════════════════
                🚀 **TRUE BATCH APPROACH** (Most Efficient: ~30-45 steps for all 23 properties)
                ═══════════════════════════════════════════════════════════════════════════════════
                
                **PHASE 1: COMPLETE PAGE SCAN** (Target: 5-10 steps)
                ───────────────────────────────────────────────────────────────────────────────────
                1. Navigate to the URL
                2. Scroll systematically from TOP to BOTTOM of ENTIRE page
                3. Continue scrolling until you reach the absolute bottom (no new content loads)
                4. Do NOT click any download buttons yet - just scan and count them
                5. Mental note: "Found X download buttons total" (should be ~23)
                6. Return to TOP of page when scanning is complete
                
                **PHASE 2: RAPID BUTTON CLICKING** (Target: 10-15 steps)  
                ───────────────────────────────────────────────────────────────────────────────────
                1. Starting from TOP of page, click EVERY "Download Brochure" button you can see
                2. Click buttons rapidly with 1-2 second delays between clicks
                3. Do NOT handle PDF tabs yet - let them accumulate in background
                4. Scroll down and continue clicking ALL download buttons
                5. Keep clicking until you've clicked every single download button on the page
                6. Each click will open a PDF in a new tab - this is expected
                7. Continue until you've clicked ~23 buttons total
                8. Do NOT switch to PDF tabs during this phase
                
                **PHASE 3: BATCH PDF PROCESSING** (Target: 15-20 steps)
                ───────────────────────────────────────────────────────────────────────────────────
                1. Now you should have ~23 PDF tabs open
                2. Go through each PDF tab systematically:
                   - Switch to tab → Call 'download_pdf_direct' → Close tab → Move to next
                3. Process ALL PDF tabs until only the main listings page remains
                4. Skip any duplicate files (download_pdf_direct will detect them)
                5. Continue until all PDF tabs are processed
                
                ═══════════════════════════════════════════════════════════════════════════════════
                ⚡ **EFFICIENCY RULES**
                ═══════════════════════════════════════════════════════════════════════════════════
                
                **Phase 1 Rules:**
                ✅ ONLY scroll and scan - no clicking buttons
                ✅ Count total download buttons found
                ✅ Load all page content completely
                ❌ Do NOT click any download buttons in Phase 1
                ❌ Do NOT handle any PDFs in Phase 1
                
                **Phase 2 Rules:**
                ✅ Click every download button as fast as possible
                ✅ Let PDF tabs accumulate in background
                ✅ Continue clicking until all buttons clicked
                ❌ Do NOT switch to PDF tabs during Phase 2
                ❌ Do NOT try to download PDFs during Phase 2
                ❌ Do NOT close any tabs during Phase 2
                
                **Phase 3 Rules:**
                ✅ Process ALL accumulated PDF tabs systematically
                ✅ Download each PDF using 'download_pdf_direct'
                ✅ Close each tab after downloading
                ❌ Do NOT return to main page between each PDF
                ❌ Do NOT click more download buttons during Phase 3
                
                ═══════════════════════════════════════════════════════════════════════════════════
                🎯 **SUCCESS CRITERIA**
                ═══════════════════════════════════════════════════════════════════════════════════
                
                - **Phase 1 Complete**: When entire page scanned and ~23 download buttons located
                - **Phase 2 Complete**: When ALL ~23 download buttons have been clicked
                - **Phase 3 Complete**: When all PDF tabs processed and only main page remains
                - **Task Complete**: When all unique PDFs downloaded to domain folder
                
                **EXPECTED EFFICIENCY**: 
                - Phase 1: 5-10 steps (scan only)
                - Phase 2: 10-15 steps (click all buttons)  
                - Phase 3: 15-20 steps (process all PDFs)
                - **Total: 30-45 steps for all 23 properties**
                
                **START**: Begin Phase 1 - scan entire page systematically without clicking anything.
                """,
                llm=self.llm,
                browser_session=self.browser_session,
                controller=controller,
                save_conversation_path=f"{self.downloads_dir}/conversation_log",  # Save conversation for debugging
            )
            
            # Run the agent with an increased step limit to allow for careful scrolling and form filling
            await agent.run(
                on_step_start=self.monitor_downloads,
                max_steps=50 # Optimized for true batch approach: 30-45 steps + buffer
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
            # Calculate final token usage and cost for this workflow
            end_time = time.time()
            end_tokens = self.token_tracker.total_tokens
            end_cost = self.token_tracker.total_cost
            
            # Update result with token usage data
            tokens_used = end_tokens - start_tokens
            cost_incurred = end_cost - start_cost
            
            result["token_usage"] = {
                "total_tokens": tokens_used,
                "input_tokens": self.token_tracker.input_tokens,
                "output_tokens": self.token_tracker.output_tokens,
                "cost_usd": cost_incurred,
                "llm_calls": self.token_tracker.call_count
            }
            result["execution_time_seconds"] = end_time - start_time
            
            # Print token usage summary for this workflow
            print(f"\n💰 Workflow Token Usage:")
            print(f"  🔢 Tokens Used: {tokens_used:,}")
            print(f"  💵 Cost: ${cost_incurred:.4f}")
            print(f"  ⏱️ Execution Time: {result['execution_time_seconds']:.1f} seconds")
            if tokens_used > 0:
                print(f"  📊 Cost per Property: ${cost_incurred / max(1, len(self.downloaded_files)):.4f}")
                print(f"  📊 Tokens per Property: {tokens_used / max(1, len(self.downloaded_files)):.0f}")
            
            # Close browser session
            try:
                await self.browser_session.close()
            except:
                pass
        
        return result

    async def monitor_downloads(self, agent):
        """Enhanced monitor with comprehensive download tracking"""
        try:
            # Set up download handlers if not already done
            await self.setup_download_handlers()
            
            page = await agent.browser_session.get_current_page()
            current_url = page.url
            
            # Log progress with step count
            step_count = len(agent.state.history.model_actions()) if hasattr(agent, 'state') and agent.state else 0
            print(f"\n📍 Step {step_count}: {current_url}")
            
            # Show comprehensive tracking info
            current_pdfs = list(self.downloads_dir.glob("*.pdf"))
            unique_downloads = len(self.downloaded_urls)
            unique_files = len(self.downloaded_filenames)
            total_files = len(current_pdfs)
            
            print(f"📊 DOWNLOAD STATUS:")
            print(f"  🎯 Unique URLs downloaded: {unique_downloads}")
            print(f"  📄 Unique filenames: {unique_files}")
            print(f"  📁 Total PDFs in folder: {total_files}")
            print(f"  🏠 Properties processed: {len(self.property_addresses)}")
            
            # Show recent downloads
            if current_pdfs:
                newest_pdfs = sorted(current_pdfs, key=lambda x: x.stat().st_mtime, reverse=True)[:3]
                print(f"📄 Recent files in {self.downloads_dir.name}/:")
                for pdf in newest_pdfs:
                    size_kb = pdf.stat().st_size // 1024
                    print(f"  • {pdf.name} ({size_kb} KB)")
            
            # Check for potential download buttons on current page
            try:
                download_selectors = [
                    'a[href*=".pdf"]',
                    'button:has-text("Download")',
                    'a:has-text("Download")',
                    '[class*="download"]',
                    'button:has-text("Brochure")',
                    'a:has-text("Brochure")'
                ]
                
                total_buttons = 0
                for selector in download_selectors:
                    try:
                        count = await page.locator(selector).count()
                        total_buttons += count
                    except:
                        pass
                
                if total_buttons > 0:
                    print(f"🎯 Found {total_buttons} potential download elements on current page")
                    
                # If we have multiple tabs, report that too
                context = page.context
                all_pages = context.pages
                if len(all_pages) > 1:
                    print(f"📑 Browser tabs open: {len(all_pages)}")
                    for i, tab in enumerate(all_pages):
                        tab_url = tab.url
                        if tab_url.endswith('.pdf'):
                            print(f"  📄 Tab {i+1}: PDF - {tab_url.split('/')[-1]}")
                        else:
                            print(f"  🌐 Tab {i+1}: {tab_url[:50]}...")
                            
            except Exception as button_check_error:
                print(f"⚠️ Could not check for download buttons: {button_check_error}")
                
            # Provide guidance based on current state
            if step_count > 10 and total_files < 5:
                print("💡 SUGGESTION: Make sure to scroll through entire page to find all properties")
            elif step_count > 20 and unique_downloads == 0:
                print("💡 SUGGESTION: Try clicking download buttons and handling PDF tabs")
            elif unique_downloads > 0 and unique_downloads < 10:
                print("💡 SUGGESTION: Continue finding remaining properties - ~23 total expected")
                
        except Exception as e:
            print(f"Monitor error: {e}")

    async def batch_download(self, urls: list) -> list:
        """Download OM/Flyers from multiple URLs with comprehensive cost tracking"""
        results = []
        
        # Track cumulative costs across all URLs
        total_start_time = time.time()
        batch_start_tokens = self.token_tracker.total_tokens
        batch_start_cost = self.token_tracker.total_cost
        
        print(f"🚀 Starting batch download of {len(urls)} URLs")
        print(f"💰 Initial token count: {batch_start_tokens:,} tokens, ${batch_start_cost:.4f}")
        
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
        
        # Calculate total batch statistics
        total_end_time = time.time()
        batch_end_tokens = self.token_tracker.total_tokens
        batch_end_cost = self.token_tracker.total_cost
        
        batch_tokens_used = batch_end_tokens - batch_start_tokens
        batch_cost_incurred = batch_end_cost - batch_start_cost
        batch_execution_time = total_end_time - total_start_time
        
        print(f"\n🎯 BATCH COMPLETION SUMMARY:")
        print(f"  📊 Total URLs Processed: {len(urls)}")
        print(f"  🔢 Total Tokens Used: {batch_tokens_used:,}")
        print(f"  💵 Total Cost: ${batch_cost_incurred:.4f}")
        print(f"  ⏱️ Total Time: {batch_execution_time / 60:.1f} minutes")
        if batch_tokens_used > 0:
            print(f"  📊 Average Cost per URL: ${batch_cost_incurred / len(urls):.4f}")
            print(f"  📊 Average Tokens per URL: {batch_tokens_used / len(urls):.0f}")
        
        return results

def print_results_summary(results: list, token_tracker: TokenTrackingCallback = None):
    """Print a comprehensive summary of download results including token usage and costs"""
    print("\n" + "="*60)
    print("📊 DOWNLOAD SUMMARY")
    print("="*60)
    
    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]
    
    # Download statistics
    print(f"✅ Successful downloads: {len(successful)}")
    print(f"❌ Failed downloads: {len(failed)}")
    
    # File statistics
    total_files = sum(len(r.get("downloaded_files", [])) for r in successful)
    print(f"📄 Total files downloaded: {total_files}")
    
    # Token and cost statistics
    total_tokens = sum(r.get("token_usage", {}).get("total_tokens", 0) for r in results)
    total_cost = sum(r.get("token_usage", {}).get("cost_usd", 0.0) for r in results)
    total_time = sum(r.get("execution_time_seconds", 0) for r in results)
    
    if total_tokens > 0:
        print(f"\n💰 COST ANALYSIS:")
        print(f"  🔢 Total Tokens: {total_tokens:,}")
        print(f"  💵 Total Cost: ${total_cost:.4f}")
        print(f"  ⏱️ Total Time: {total_time / 60:.1f} minutes")
        
        if len(results) > 1:
            print(f"  📊 Average per URL:")
            print(f"    🔢 Tokens: {total_tokens / len(results):.0f}")
            print(f"    💵 Cost: ${total_cost / len(results):.4f}")
            print(f"    ⏱️ Time: {total_time / len(results) / 60:.1f} minutes")
        
        if total_files > 0:
            print(f"  📊 Efficiency metrics:")
            print(f"    🔢 Tokens per file: {total_tokens / total_files:.0f}")
            print(f"    💵 Cost per file: ${total_cost / total_files:.4f}")
    
    if successful:
        print("\n🎉 Successfully Downloaded:")
        for result in successful:
            url_short = result["url"][:50] + "..." if len(result["url"]) > 50 else result["url"]
            file_count = len(result.get("downloaded_files", []))
            tokens = result.get("token_usage", {}).get("total_tokens", 0)
            cost = result.get("token_usage", {}).get("cost_usd", 0.0)
            print(f"  • {file_count} files from {url_short}")
            if tokens > 0:
                print(f"    💰 {tokens:,} tokens, ${cost:.4f}")
    
    if failed:
        print("\n❌ Failed Downloads:")
        for result in failed:
            url_short = result["url"][:50] + "..." if len(result["url"]) > 50 else result["url"]
            tokens = result.get("token_usage", {}).get("total_tokens", 0)
            cost = result.get("token_usage", {}).get("cost_usd", 0.0)
            print(f"  • {url_short}: {result['error']}")
            if tokens > 0:
                print(f"    💰 {tokens:,} tokens, ${cost:.4f} (still incurred)")
    
    # Show overall token tracker summary if available
    if token_tracker:
        token_tracker.print_detailed_summary()

async def main():
    """Enhanced main function with comprehensive token tracking and cost analysis"""
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
        print(f"📁 Downloads will be saved to: {downloader.base_downloads_dir}")
        print(f"🤖 Using GPT-4o with token tracking enabled")
        print(f"💰 Pricing: ${GPT4O_PRICING['input_tokens_per_1k']}/1k input, ${GPT4O_PRICING['output_tokens_per_1k']}/1k output tokens")
        
        if len(urls) == 1:
            result = await downloader.download_om_flyer(urls[0])
            print_results_summary([result], downloader.token_tracker)
        else:
            results = await downloader.batch_download(urls)
            print_results_summary(results, downloader.token_tracker)
            
    except Exception as e:
        print(f"❌ Error: {e}")
        if "OPENAI_API_KEY" in str(e):
            print("💡 Set your OpenAI API key: export OPENAI_API_KEY='your-key-here'")

if __name__ == "__main__":
    asyncio.run(main()) 