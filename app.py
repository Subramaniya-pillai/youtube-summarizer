import streamlit as st
import google.generativeai as genai
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, VideoUnavailable
from urllib.parse import urlparse, parse_qs
import yt_dlp

# Skip .env file completely and ask for API key directly
st.sidebar.header("🔑 API Configuration")
api_key = st.sidebar.text_input("Enter your Google API Key:", type="password", help="Get your API key from https://makersuite.google.com/app/apikey")

if not api_key:
    st.error("❌ Please enter your Google API key in the sidebar to continue!")
    st.info("💡 Get your free API key from: https://makersuite.google.com/app/apikey")
    st.stop()

try:
    genai.configure(api_key=api_key)
    st.sidebar.success("✅ API key configured!")
except Exception as e:
    st.sidebar.error(f"❌ Invalid API key: {str(e)}")
    st.stop()

# Prompt template for Gemini
prompt = """
You are a YouTube video summarizer. You will be taking the transcript text
and summarizing the entire video and providing the important summary in points
within 250 words. Please provide the summary of the text given here:  
"""

# Function to extract YouTube video ID from URL
def extract_video_id(url):
    try:
        parsed_url = urlparse(url)
        
        # Handle different YouTube URL formats
        if 'youtu.be' in parsed_url.netloc:
            # Short format: https://youtu.be/VIDEO_ID
            video_id = parsed_url.path[1:]  # Remove the leading '/'
            return video_id if video_id else None
        elif 'youtube.com' in parsed_url.netloc or 'www.youtube.com' in parsed_url.netloc:
            # Long format: https://www.youtube.com/watch?v=VIDEO_ID
            video_id = parse_qs(parsed_url.query).get("v")
            return video_id[0] if video_id else None
        else:
            return None
    except Exception:
        return None

# Alternative function using yt-dlp to actually extract transcript
def extract_transcript_with_ytdlp(video_url):
    try:
        import tempfile
        
        # Create a temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            ydl_opts = {
                'writesubtitles': True,
                'writeautomaticsub': True,
                'subtitleslangs': ['en'],
                'subtitlesformat': 'vtt',
                'skip_download': True,
                'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                
                # Check available subtitles
                subtitles = info.get('subtitles', {})
                automatic_captions = info.get('automatic_captions', {})
                
                # Try to download subtitles
                if 'en' in subtitles:
                    st.write("Found manual English subtitles, downloading...")
                    ydl.download([video_url])
                    
                    # Look for the downloaded subtitle file
                    for file in os.listdir(temp_dir):
                        if file.endswith('.en.vtt'):
                            vtt_file = os.path.join(temp_dir, file)
                            st.write(f"Found VTT file: {file}")
                            return extract_text_from_vtt(vtt_file)
                    
                    st.write("VTT file not found after download")
                    return "VTT file not found"
                            
                elif 'en' in automatic_captions:
                    st.write("Found auto-generated English captions, downloading...")
                    ydl.download([video_url])
                    
                    # Look for the downloaded subtitle file
                    for file in os.listdir(temp_dir):
                        if file.endswith('.en.vtt'):
                            vtt_file = os.path.join(temp_dir, file)
                            st.write(f"Found VTT file: {file}")
                            return extract_text_from_vtt(vtt_file)
                    
                    st.write("VTT file not found after download")
                    return "VTT file not found"
                
                return "No English subtitles found"
                
    except Exception as e:
        return f"yt-dlp error: {str(e)}"

def extract_text_from_vtt(vtt_file):
    try:
        import re
        with open(vtt_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        st.write(f"Debug: VTT file content preview: {content[:200]}...")
        
        # Remove VTT formatting and extract text
        # Remove timestamps and formatting
        text = re.sub(r'\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}', '', content)
        text = re.sub(r'<[^>]+>', '', text)  # Remove HTML tags
        text = re.sub(r'WEBVTT\n\n', '', text)  # Remove VTT header
        text = re.sub(r'\n+', ' ', text)  # Replace multiple newlines with space
        text = re.sub(r'^\d+\n', '', text, flags=re.MULTILINE)  # Remove line numbers
        
        # Clean up extra whitespace
        text = re.sub(r'\s+', ' ', text)  # Replace multiple spaces with single space
        text = text.strip()
        
        st.write(f"Debug: Extracted text length: {len(text)} characters")
        
        if len(text) < 10:
            return f"Error: Extracted text too short. VTT content: {content[:500]}"
        
        return text
        
    except Exception as e:
        return f"Error reading VTT file: {str(e)}"

# Function to fetch transcript text
def extract_transcript_details(video_id):
    try:
        # Use yt-dlp as primary method since youtube-transcript-api has issues
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        st.write("Using yt-dlp to extract transcript...")
        
        result = extract_transcript_with_ytdlp(video_url)
        
        # Check if yt-dlp succeeded (has actual transcript text)
        if len(result) > 100 and not result.startswith("Error") and not result.startswith("No"):
            st.write("✅ Successfully extracted transcript with yt-dlp!")
            return result
        else:
            # Fallback to youtube-transcript-api if yt-dlp fails
            st.write("yt-dlp failed, trying youtube-transcript-api...")
            try:
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
                transcript = transcript_list.find_transcript(['en'])
                transcript_data = transcript.fetch()
                transcript_text = " ".join([i["text"] for i in transcript_data])
                st.write("Success with youtube-transcript-api!")
                return transcript_text
            except Exception as api_error:
                st.write(f"youtube-transcript-api also failed: {str(api_error)}")
                return f"Both methods failed. yt-dlp result: {result}"
        
    except VideoUnavailable:
        return "Error: The video is unavailable or private."
    except TranscriptsDisabled:
        return "Error: Transcripts are disabled for this video."
    except Exception as e:
        return f"Error: {str(e)}"

# Function to get summary using Gemini
def generate_gemini_content(transcript_text, prompt):
    model = genai.GenerativeModel("gemini-2.0-flash-001")
    response = model.generate_content(prompt + transcript_text)
    return response.text

# Streamlit app UI
st.title("🎥 YouTube Video Summarizer")

youtube_link = st.text_input("Enter YouTube Video Link:")

if youtube_link:
    video_id = extract_video_id(youtube_link)
    if video_id:
        st.image(f"http://img.youtube.com/vi/{video_id}/0.jpg", width='stretch')
    else:
        st.error("❌ Invalid YouTube URL. Please check and try again.")

if st.button("Get Detailed Notes"):
    video_id = extract_video_id(youtube_link)
    if not video_id:
        st.error("❌ Invalid YouTube link format.")
    else:
        transcript_text = extract_transcript_details(video_id)

        if transcript_text.startswith("Error:"):
            st.error(transcript_text)
        else:
            summary = generate_gemini_content(transcript_text, prompt)
            st.markdown("## 📝 Detailed Notes:")
            st.write(summary)
# developer credit
st.markdown("---")
st.markdown(
    '<div style="text-align: right; color: gray; font-size: 0.8em;">Developed by Subramani</div>',
    unsafe_allow_html=True
)
