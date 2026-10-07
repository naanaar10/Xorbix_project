"""Visual system. Grotesk for data and interface; serif only for words an agent wrote."""

INK = "#10282E"
TEAL = "#2D6E66"
RASPBERRY = "#C03A4E"
INDIGO = "#4B4FC4"
SLATE = "#6B7F82"
MINERAL = "#EDF1EF"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Familjen+Grotesk:wght@400;500;600;700&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;1,6..72,400&display=swap');

html, body, [class*="st-"], .stMarkdown, button, input, textarea, select {{
  font-family: 'Familjen Grotesk', system-ui, sans-serif;
  font-variant-numeric: tabular-nums;
}}
.block-container {{ padding-top: 2rem; max-width: 1180px; }}
h1, h2, h3 {{ font-family: 'Familjen Grotesk', sans-serif; color: {INK}; letter-spacing: -0.01em; }}
h1 {{ font-weight: 700; font-size: 2.1rem; margin-bottom: 0; }}

[data-testid="stMarkdownContainer"] .lede {{ color: {SLATE}; font-size: 1.05rem; max-width: 62ch; margin: 0.2rem 0 1.4rem; }}
[data-testid="stMarkdownContainer"] .headline {{ font-size: 1.65rem; font-weight: 600; line-height: 1.25; max-width: 30ch; margin: 0; }}
[data-testid="stMarkdownContainer"] .subline {{ color: {SLATE}; font-size: 1rem; margin: 0.35rem 0 0; max-width: 64ch; }}

[data-testid="stMarkdownContainer"] .agent-voice {{ font-family: 'Newsreader', Georgia, serif; font-size: 1.22rem; line-height: 1.5;
  color: {INK}; max-width: 68ch; }}
[data-testid="stMarkdownContainer"] .agent-voice.small {{ font-size: 1.05rem; }}

.case {{ border-left: 4px solid {RASPBERRY}; background: #F6F8F7; padding: 1rem 1.25rem 0.9rem;
  margin: 0 0 1.1rem; }}
.case .who {{ display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap;
  font-weight: 600; font-size: 1.05rem; }}
.case .stake {{ color: {RASPBERRY}; }}
.case .evidence {{ color: {SLATE}; font-size: 0.95rem; margin-top: 0.6rem; max-width: 80ch; }}
.case .fix {{ margin-top: 0.6rem; font-size: 0.95rem; }}
.case .handoff {{ color: {INDIGO}; font-weight: 600; font-size: 0.95rem; margin-top: 0.5rem; }}

.step {{ display: grid; grid-template-columns: 9.5rem 1fr; gap: 0.75rem; padding: 0.35rem 0;
  border-bottom: 1px solid #D5DDDB; font-size: 0.95rem; }}
.step .agent {{ color: {SLATE}; }}
.step.write .what {{ color: {INDIGO}; font-weight: 600; }}

.metric-row {{ display: flex; gap: 2.5rem; flex-wrap: wrap; margin: 0.5rem 0 1rem; }}
.metric-row .value {{ font-size: 1.6rem; font-weight: 600; }}
.metric-row .label {{ color: {SLATE}; font-size: 0.9rem; }}

[data-testid="stSidebar"] {{ background: #E1E8E6; }}
:focus-visible {{ outline: 2px solid {INDIGO}; outline-offset: 2px; }}
@media (prefers-reduced-motion: reduce) {{ * {{ animation: none !important; transition: none !important; }} }}
</style>
"""


def html_block(markup: str) -> str:
    """Streamlit markdown treats $...$ as math; escape dollars in raw HTML blocks."""
    return markup.replace("$", "&#36;")
