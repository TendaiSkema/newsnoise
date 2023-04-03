import os
import imgkit

def render_html_template(text, image_path=None, template='matches/template.html', css_path='matches/style.css'):
    """
    Renders an HTML template with the given text and image, and saves the resulting image data as a base64-encoded
    PNG file.

    Args:
        text (str): The text to be displayed in the HTML template.
        image_path (str, optional): The path to the image to be used as the background for the HTML template.
            If not provided, a default image will be used.
        template (str, optional): The path to the HTML template file to be used. Defaults to 'template.html'.
    """
    if image_path is None:
        image_path = 'matches/No_Preview_image_2.png'

    image_url_path = 'file:///' + os.path.normpath(os.path.abspath(image_path)).replace('\\', '/')
    # Read the CSS style file
    with open(css_path) as f:
        css = f.read()

    # Read the template HTML file
    with open(template) as f:
        html = f.read()

    # Replace placeholders with actual content
    html = html.replace('{{ css }}', css)
    html = html.replace('{{ text }}', text)
    html = html.replace('{{ image_path }}', image_url_path)

    kitoptions = {
        "enable-local-file-access": None,
        "width": 1920, 
        "height": 1080
    }

    # Render the HTML to a PNG image using imgkit
    imgkit.from_string(html, image_path, options=kitoptions)
    print('Image saved to out.png')

