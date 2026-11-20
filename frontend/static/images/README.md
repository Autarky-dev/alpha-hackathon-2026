# Images

Place local event posters, venue photos, and brand assets in this folder. Reference them from templates with:

```jinja2
{{ url_for('static', path='images/your-image.webp') }}
```

Use optimized WebP/AVIF images and provide meaningful `alt` text in the HTML.
