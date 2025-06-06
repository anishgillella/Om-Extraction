# OM/Flyer Downloader

Automated Browser Use agent for downloading Offering Memorandums and Flyers from real estate property pages.

## Features

✅ **LLM-Driven Navigation**: Uses GPT-4o to intelligently navigate property pages  
✅ **Automatic Form Handling**: Fills out lead capture forms with predefined data  
✅ **Multi-Method Download**: Browser automation + direct HTTP downloads for reliability  
✅ **Visual Feedback**: Visible browser for GIF recording and monitoring  
✅ **Robust Error Handling**: Multiple fallback methods and comprehensive logging  
✅ **Batch Processing**: Support for multiple URLs in sequence  

## Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd TheusAI
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   playwright install
   ```

3. **Set up environment variables**
   Create a `.env` file with your OpenAI API key:
   ```
   OPENAI_API_KEY=your_openai_api_key_here
   ```

## Usage

### Single URL
```bash
python om_flyer_downloader.py "https://example-property-site.com/listing/123"
```

### Multiple URLs
```bash
python om_flyer_downloader.py "https://site1.com/property1" "https://site2.com/property2"
```

### Example with CEG Advisors
```bash
python om_flyer_downloader.py "https://cegadvisors.com/property/kearny-square/"
```

## How It Works

### 1. **Browser Use Agent Navigation**
- Opens property page in visible browser
- Intelligently searches for download buttons containing terms like:
  - "Download Brochure", "LEASE BROCHURE"
  - "Offering Memorandum", "OM", "Flyer"
  - "Marketing Package", "Brochure"
- Clicks download elements and handles form popups

### 2. **PDF URL Capture**
- Monitors browser tabs during navigation
- Captures PDF URLs when agent opens them
- Tracks all PDF links found during execution

### 3. **Direct HTTP Download**
- Downloads original PDF files via HTTP requests
- Uses proper headers to avoid 403 errors
- Saves files to specified downloads directory

### 4. **Form Auto-Fill**
If forms appear, they are automatically filled with:
- **Name**: John Doe
- **Email**: johndoe@email.com
- **Phone**: 555-123-4567
- **Company**: Real Estate Investments LLC

## Configuration

### Downloads Directory
Files are saved to: `/Users/anishgillella/Desktop/Stuff/Theus/TheusAI/downloads/`

### Browser Settings
- **Headless**: False (visible for GIF recording)
- **Viewport**: 1280x1024
- **Highlights**: Element highlighting enabled
- **Wait Time**: 3 seconds for network idle

## Output

### Console Output
```
🏠 Starting OM/Flyer download workflow for: https://example.com/property
📁 Downloads will be saved to: /path/to/downloads

🤖 Method 1: Using Browser Use Agent...
📍 Step 1: https://example.com/property
🎯 Found 1 potential download elements
🎯 Found PDF URL: https://example.com/documents/property.pdf
✅ Downloaded: /path/to/downloads/Property-Brochure.pdf
📄 File size: 2048 KB

🎉 Success! Downloaded 1 file(s):
  • Property-Brochure.pdf
```

### File Structure
```
TheusAI/
├── om_flyer_downloader.py    # Main downloader script
├── requirements.txt          # Python dependencies
├── .env                     # Environment variables (not in git)
├── downloads/               # Downloaded PDFs (not in git)
└── README.md               # This file
```

## Supported Sites

The downloader works with any real estate property page that has:
- Download buttons/links for PDFs
- Standard form fields (name, email, phone)
- Accessible PDF URLs

**Tested with:**
- CEG Advisors property pages
- Standard real estate marketing sites

## Error Handling

The script includes multiple fallback methods:

1. **Browser Use Agent** - LLM-driven navigation
2. **PDF URL Capture** - Direct HTTP download
3. **Playwright API** - Low-level browser automation

If one method fails, the next is automatically attempted.

## Dependencies

- `browser-use` - AI browser automation
- `playwright` - Browser automation library
- `langchain-openai` - OpenAI ChatGPT integration
- `aiohttp` - Async HTTP client for downloads
- `python-dotenv` - Environment variable management

## Requirements

- Python 3.8+
- OpenAI API key
- Internet connection
- macOS/Linux/Windows

## License

MIT License 