
import google.generativeai as genai
import PIL.Image
import os
import io

genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
img = PIL.Image.new('RGB', (100, 100), color = 'red')

model = genai.GenerativeModel('gemini-1.5-flash')
response = model.generate_content(['What color is this image?', img])
print(response.text)

