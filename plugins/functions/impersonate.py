import subprocess

def impersonate_final_url(url: str) -> str:
    """
    CRITICAL FUNCTION — DO NOT MODIFY.
    Uses curl-impersonate-chrome to resolve final redirected streaming URL.
    Fixes: get_stream -> okcdn zero-byte issues.
    Returns the final CDN URL or original if anything fails.
    """
    try:
        cmd = ["curl-impersonate-chrome", "-I", "-L", url]
        result = subprocess.run(cmd, capture_output=True, text=True)

        output = result.stdout.split("\n")
        final_url = url

        for line in output:
            if line.lower().startswith("location:"):
                final_url = line.split(":", 1)[1].strip()

        return final_url

    except Exception:
        # Never break calling code; always return original URL on failure.
        return url
