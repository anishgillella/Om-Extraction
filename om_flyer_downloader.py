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
from browser_use import Agent, BrowserSession, BrowserProfile
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class OMFlyerDownloader:
    def __init__(self, openai_api_key=None):
        """Initialize the OM/Flyer downloader with Browser Use agent"""
        self.api_key = openai_api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY environment variable or pass it directly.")
        
        # Set up downloads directory - Fixed to your specified path
        self.downloads_dir = Path("/Users/anishgillella/Desktop/Stuff/Theus/TheusAI/downloads")
        self.downloads_dir.mkdir(exist_ok=True, parents=True)
        
        # Initialize LLM
        self.llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0.0,
            api_key=self.api_key
        )
        
        # Configure browser for visibility and downloads
        self.browser_profile = BrowserProfile(
            headless=False,  # Show browser for GIF recording
            viewport={"width": 1280, "height": 1024},
            wait_for_network_idle_page_load_time=3.0,
            highlight_elements=True,  # Visual feedback
        )
        
        self.browser_session = BrowserSession(
            browser_profile=self.browser_profile
        )
        
        # Track downloads
        self.downloaded_files = []
        self.pdf_urls_found = []

    async def download_pdf_from_url(self, pdf_url: str, filename: str = None) -> Path | None:
        """Download a PDF file directly from a URL using HTTP request"""
        try:
            print(f"🌐 Downloading PDF from: {pdf_url}")
            
            # Create filename if not provided
            if not filename:
                filename = pdf_url.split('/')[-1]
                if not filename.endswith('.pdf'):
                    filename += '.pdf'
            
            # Clean filename
            clean_filename = filename.replace("/", "-").replace("\\", "-")
            download_path = self.downloads_dir / clean_filename
            
            # Set up headers to avoid 403 errors
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                'Accept': 'application/pdf,application/octet-stream,*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
            
            # Add referer if it's from the same domain
            if 'cegadvisors.com' in pdf_url:
                headers['Referer'] = 'https://cegadvisors.com/property/kearny-square/'
            
            # Download the file
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(pdf_url) as response:
                    if response.status == 200:
                        content = await response.read()
                        
                        # Save the file
                        with open(download_path, 'wb') as f:
                            f.write(content)
                        
                        self.downloaded_files.append(download_path)
                        print(f"✅ Downloaded: {download_path}")
                        print(f"📄 File size: {len(content) // 1024} KB")
                        
                        return download_path
                    else:
                        print(f"❌ Failed to download PDF: HTTP {response.status}")
                        return None
                        
        except Exception as e:
            print(f"❌ PDF download error: {e}")
            return None

    async def extract_pdf_urls_from_page(self) -> list:
        """Extract PDF URLs from the current page"""
        try:
            page = await self.browser_session.get_current_page()
            pdf_urls = []
            
            # Get all tabs and check for PDF URLs
            context = page.context
            pages = context.pages
            
            for page_obj in pages:
                url = page_obj.url
                if url.endswith('.pdf') or 'pdf' in url.lower():
                    pdf_urls.append(url)
                    print(f"🎯 Found PDF URL: {url}")
            
            return pdf_urls
            
        except Exception as e:
            print(f"Error extracting PDF URLs: {e}")
            return []

    async def setup_download_handling(self):
        """Configure the browser to handle downloads properly"""
        try:
            # Ensure browser session is active first
            if not hasattr(self.browser_session, '_page') or self.browser_session._page is None:
                # Initialize browser session properly
                await self.browser_session.start()
            
            page = await self.browser_session.get_current_page()
            
            if page is None:
                print("⚠️ Could not get current page, skipping download setup")
                return None
            
            # Set download behavior
            await page.context.set_default_timeout(30000)
            
            # Handle download events
            async def handle_download(download):
                try:
                    # Get the suggested filename
                    suggested_filename = download.suggested_filename or f"document_{int(time.time())}.pdf"
                    
                    # Clean filename
                    clean_filename = suggested_filename.replace("/", "-").replace("\\", "-")
                    
                    # Create full path for the download
                    download_path = self.downloads_dir / clean_filename
                    
                    # Save the download
                    await download.save_as(download_path)
                    self.downloaded_files.append(download_path)
                    print(f"✅ Downloaded: {download_path}")
                    print(f"📄 File size: {download_path.stat().st_size // 1024} KB")
                    
                    return download_path
                except Exception as e:
                    print(f"❌ Download error: {e}")
            
            # Listen for download events
            page.on("download", handle_download)
            
            return page
            
        except Exception as e:
            print(f"⚠️ Download setup error: {e}")
            return None

    async def download_with_playwright_api(self, url: str):
        """Alternative method using Playwright's download API directly"""
        try:
            page = await self.browser_session.get_current_page()
            
            # Navigate to the URL
            print(f"🌐 Navigating to: {url}")
            await page.goto(url)
            await page.wait_for_load_state('networkidle')
            
            # Look for download links/buttons
            print("🔍 Looking for download elements...")
            
            # Try different selectors for download elements
            selectors = [
                'a[href*=".pdf"]',
                'a[href*="download"]', 
                '[class*="download"]',
                'button:has-text("Download")',
                'a:has-text("Download")',
                'a:has-text("Brochure")',
                'button:has-text("Brochure")'
            ]
            
            download_elements = []
            for selector in selectors:
                elements = await page.locator(selector).all()
                download_elements.extend(elements)
            
            print(f"🎯 Found {len(download_elements)} potential download elements")
            
            # Remove duplicates
            unique_elements = []
            seen_texts = set()
            for element in download_elements:
                try:
                    text = await element.text_content()
                    if text and text not in seen_texts:
                        unique_elements.append(element)
                        seen_texts.add(text)
                        print(f"   • {text}")
                except:
                    unique_elements.append(element)
            
            # Try to download from each unique element
            for i, link in enumerate(unique_elements):
                try:
                    print(f"🖱️ Attempting download from element {i+1}...")
                    
                    # Start waiting for download before clicking
                    async with page.expect_download(timeout=10000) as download_info:
                        await link.click()
                    
                    download = await download_info.value
                    
                    # Save to your specified directory
                    filename = download.suggested_filename or f"document_{i+1}_{int(time.time())}.pdf"
                    clean_filename = filename.replace("/", "-").replace("\\", "-")
                    download_path = self.downloads_dir / clean_filename
                    
                    await download.save_as(download_path)
                    self.downloaded_files.append(download_path)
                    print(f"✅ Downloaded: {download_path}")
                    print(f"📄 File size: {download_path.stat().st_size // 1024} KB")
                    
                    # Wait a bit between downloads
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    print(f"⚠️ Failed to download from element {i+1}: {e}")
                    continue
                    
        except Exception as e:
            print(f"❌ Download error: {e}")

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
            
            # Method 1: Try Browser Use Agent first
            print("\n🤖 Method 1: Using Browser Use Agent...")
            
            # Setup download handling (optional, proceed even if it fails)
            page = await self.setup_download_handling()
            if page:
                print("✅ Download event handling setup complete")
            else:
                print("⚠️ Download event handling failed, proceeding with agent anyway")
            
            # Create agent with download-focused task
            agent = Agent(
                task=f"""Navigate to {url} and find PDF download links by:
                1. Looking for download buttons, PDF links, or document icons containing terms like:
                   - "Download Brochure", "LEASE BROCHURE", "Download", "Brochure"
                   - "Offering Memorandum", "OM", "Flyer", "Marketing Package"
                2. Clicking on them to open PDF files in new tabs
                3. If forms appear, fill with: Name: John Doe, Email: johndoe@email.com, Phone: 555-123-4567
                4. IMPORTANT: Switch to any new tabs that opened with PDF files
                5. Stay on the PDF tab for a few moments to ensure the URL is captured
                6. Verify the PDF content is visible before completing""",
                llm=self.llm,
                browser_session=self.browser_session
            )
            
            # Run the agent
            await agent.run(
                on_step_start=self.monitor_downloads,
                max_steps=10
            )
            
            result["steps_completed"].append("Browser Use agent completed")
            
            # Wait for any operations to complete
            await asyncio.sleep(2)
            
            # Method 2: Download PDF URLs captured during monitoring
            print("\n🎯 Method 2: Downloading captured PDF URLs directly...")
            
            if self.pdf_urls_found:
                for pdf_url in self.pdf_urls_found:
                    # Extract filename from URL
                    filename = pdf_url.split('/')[-1]
                    if 'kearny' in filename.lower():
                        filename = "Kearny-Square-Lease.pdf"
                    elif not filename.endswith('.pdf'):
                        filename += '.pdf'
                    
                    downloaded_file = await self.download_pdf_from_url(pdf_url, filename)
                    if downloaded_file:
                        result["steps_completed"].append(f"Downloaded PDF from {pdf_url}")
                        print(f"✅ Successfully downloaded original PDF file!")
            else:
                print("❌ No PDF URLs were captured during agent execution")
            
            # Method 3: Try direct Playwright API if still no downloads
            if not self.downloaded_files:
                print("\n🎯 Method 3: Using Direct Playwright API...")
                await self.download_with_playwright_api(url)
                result["steps_completed"].append("Playwright API attempted")
            
            # Check results
            if self.downloaded_files:
                result["success"] = True
                result["downloaded_files"] = [str(f) for f in self.downloaded_files]
                result["steps_completed"].append("Download verified")
                print(f"\n🎉 Success! Downloaded {len(self.downloaded_files)} file(s):")
                for file_path in self.downloaded_files:
                    print(f"  • {file_path.name}")
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
        """Hook to monitor download progress and capture PDF URLs"""
        try:
            page = await agent.browser_session.get_current_page()
            current_url = page.url
            
            # Log progress
            step_count = len(agent.state.history.model_actions()) if hasattr(agent, 'state') and agent.state else 0
            print(f"📍 Step {step_count}: {current_url}")
            
            # Check if we're on a PDF URL
            if current_url.endswith('.pdf') or 'pdf' in current_url.lower():
                if current_url not in self.pdf_urls_found:
                    self.pdf_urls_found.append(current_url)
                    print(f"🎯 Found PDF URL: {current_url}")
            
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

    def find_latest_pdf(self, min_size_kb: int = 10) -> Path | None:
        """Find the most recently downloaded PDF file with minimum size check"""
        try:
            # Check our tracked downloads first
            if self.downloaded_files:
                return self.downloaded_files[-1]  # Return most recent
                
            # Fallback to directory search
            pdf_files = list(self.downloads_dir.glob("*.pdf"))
            if pdf_files:
                recent_pdfs = []
                cutoff_time = time.time() - 120  # Last 2 minutes
                
                for pdf in pdf_files:
                    stat = pdf.stat()
                    if (stat.st_mtime > cutoff_time and 
                        stat.st_size > min_size_kb * 1024):
                        recent_pdfs.append((pdf, stat.st_mtime))
                
                if recent_pdfs:
                    return max(recent_pdfs, key=lambda x: x[1])[0]
                    
        except Exception as e:
            print(f"Error checking for downloaded PDFs: {e}")
        return None

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