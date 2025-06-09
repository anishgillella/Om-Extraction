#!/usr/bin/env python3
"""
OM/Flyer Downloader using Browser Use
Downloads Offering Memorandums and Flyers from real estate property pages
"""

import asyncio
import os
import time
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
        
        # Set up downloads directory
        self.downloads_dir = Path("/Users/anishgillella/Desktop/Stuff/Theus/TheusAI/downloads")
        self.downloads_dir.mkdir(exist_ok=True, parents=True)
        
        # Initialize LLM
        self.llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0.0,
            api_key=self.api_key
        )
        
        # Configure browser profile (remove invalid download parameters)
        self.browser_profile = BrowserProfile(
            headless=False,
            viewport={"width": 1280, "height": 1024},
            wait_for_network_idle_page_load_time=3.0,
            highlight_elements=True,
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
                1. Looking for download buttons or links like "VIEW PACKAGE", "Download Brochure", etc.
                2. IMPORTANT: If you need to scroll, use the 'scroll_down' action with `pages=0.5` to scroll half a page at a time to avoid missing the button.
                3. Clicking the download button. If a form appears, fill it out with professional data and submit it.
                   - Name: John Doe
                   - Email: johndoe@email.com
                   - Phone: 555-123-4567
                   - Company: Real Estate Investments LLC
                4. After submitting the form, find and click the final download link.
                5. CRITICAL: After clicking the final download button/link ONCE, immediately use the 'done' action after 5 seconds after clicking on the download button.
                6. DO NOT click the download button multiple times. .
                The task is complete as soon as you click the final download button.""",
                llm=self.llm,
                browser_session=self.browser_session
            )
            
            # Run the agent with an increased step limit to allow for careful scrolling and form filling
            await agent.run(
                on_step_start=self.monitor_downloads,
                max_steps=12 # Keep increased limit for form filling
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