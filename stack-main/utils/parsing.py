from __future__ import annotations
import re
import unicodedata
import json

from typing import Any, Sequence

def get_nested(
    data: Any,
    path: str,
    *,
    sep: str = ".",
    default: Any = ...,
    cast_lists: bool = True,
) -> Any:
    """
    Traverse `data` following `path` and return the located value.

    Parameters
    ----------
    data : Any
        A JSON-like object (dicts / lists / primitives).
    path : str
        String of keys/indices, e.g. "user.profile.name" or "items.0.price".
    sep : str, default "."
        Delimiter separating the path components.
    default : Any, default `...`
        Value returned if the path cannot be fully resolved.  If left as
        the sentinel `...`, a KeyError/IndexError/TypeError is raised.
    cast_lists : bool, default True
        If True, components that look like integers are treated as list
        indices; otherwise they are treated as dict keys.

    Examples
    --------
    >>> obj = {
    ...     "user": {"profile": {"name": "Janusz"}},
    ...     "items": [{"price": 19.99}, {"price": 4.50}]
    ... }
    >>> get_nested(obj, "user.profile.name")
    'Janusz'
    >>> get_nested(obj, "items.1.price")
    4.50
    >>> get_nested(obj, "items.2.price", default=None)
    None
    """
    curr: Any = data
    for component in path.split(sep):
        # Choose list index vs dict key
        if cast_lists and isinstance(curr, Sequence) and not isinstance(curr, (str, bytes)):
            # lists/tuples/whatever
            try:
                idx = int(component)
                curr = curr[idx]
                continue
            except (ValueError, IndexError):
                pass  # fall back to dict lookup if not a valid index
        try:
            curr = curr[component]
        except (KeyError, TypeError):
            if default is ...:
                raise
            return default
    return curr


def build_repair_prompt(partial_json: str, original_prompt: str) -> str:
    """
    Create a repair prompt for a truncated JSON response.

    Args:
        partial_json (str): The raw JSON fragment produced so far.
        original_prompt (str): The full prompt that was used to generate
                               the partial_json.

    Returns:
        str: A prompt to send back to the LLM to finish the JSON.
    """
    return f"""
You started generating a JSON response for the following request:

<<<START_OF_ORIGINAL_PROMPT
{original_prompt}
END_OF_ORIGINAL_PROMPT>>>

The output was cut off part-way. Below is the exact fragment you produced
(verbatim, no edits):

<<<START_OF_PARTIAL_JSON
{partial_json}
END_OF_PARTIAL_JSON>>>

TASK — CONTINUE ONLY:
1. **Resume immediately** after the last character shown above; do NOT
   repeat any existing text.
2. Emit **only** the remaining JSON needed to close every open structure
   and finish the top-level object.
3. Ensure all strings are properly closed, commas are correct, and there
   is exactly one final closing brace (}}) for the top-level object.
4. When your new text is appended to the partial JSON, the result must:
   • Parse as valid UTF-8 JSON.  
   • Conform to *all* field names, structure, and content rules stated
     in the original prompt (see above).

Output **raw JSON only** — no markdown, explanations, or prose.
""".strip()

def json_likely_truncated(txt: str) -> bool:
    stack = []
    for ch in txt:
        if ch in '{[': stack.append(ch)
        elif ch == '}' and (not stack or stack.pop() != '{'): return True
        elif ch == ']' and (not stack or stack.pop() != '['): return True
    return bool(stack) or txt.strip()[-1] not in ('}', ']')

from typing import Tuple

_CODE_FENCE_RE = re.compile(
    r"""
    ^\s*                # any leading whitespace before the opening fence
    (?P<fence>`{3,})    # ```  or  ```` … capture the exact fence length
    [ \t]*              # optional space/tab
    (?P<lang>[^\n]*)?   # optional language tag (json, yaml, etc.)
    \n                  # end of the fence-line
    (?P<body>.*?)       # the code itself – non-greedy so we can stop at…
    \n\s*               # newline, then any indent before closing fence
    (?P=fence)          # …the matching fence length captured above
    \s*$                # trailing whitespace till end-of-string
    """,
    re.DOTALL | re.VERBOSE,
)

def strip_fences(text: str) -> str:
    """
    Return the contents of the first Markdown code block in *text*,
    stripping the surrounding fences. If *text* doesn't start with a
    fenced block, the original string is returned unchanged.

    Handles:
    • Arbitrary fence length (```  ````  etc.)  
    • Optional language identifiers after the opening fence  
    • Leading/trailing whitespace around the fences  
    • Both Unix and Windows line endings  
    """
    if not text:
        return text

    match = _CODE_FENCE_RE.match(text.strip())
    if match:
        return match.group("body").rstrip()  # drop trailing whitespace inside block

    # Fallback: no leading fence detected – return as-is
    return text.strip()

def parse_selected_location_name(text):
    """
    Robustly extract selected location name from model text response.
    """
    # Pattern: look for "**Selected Location Name**: something"
    pattern = r"(?i)\*\*Selected Location Name\*\*\s*:\s*(.+)"
    match = re.search(pattern, text)
    if match:
        return match.group(1).strip()

    # Fallback: Try a looser match if formatting missing
    pattern_loose = r"(?i)Selected Location Name\s*:\s*(.+)"
    match = re.search(pattern_loose, text)
    if match:
        return match.group(1).strip()

    raise ValueError("Could not parse selected location name from match.")


def safe_json_loads(response_text):
    """
    Attempts to safely parse a model response into JSON.
    Handles common LLM mistakes like Markdown code blocks, extra text, etc.
    """

    if isinstance(response_text, dict):
        return response_text

    if not response_text or not response_text.strip():
        raise ValueError("Response is empty or blank.")

    cleaned = response_text.strip()

    # Remove Markdown code block if present
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[^\n]*\n", "", cleaned)
        cleaned = re.sub(r"\n```$", "", cleaned)

    # Try parsing normally
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass  # Continue trying other fixes

    # Try to extract the first JSON-looking object if extra text is around
    try:
        json_part = re.search(r'({.*})', cleaned, flags=re.DOTALL)
        if json_part:
            return json.loads(json_part.group(1))
    except Exception:
        pass  # Fallback to raising

    # Last resort: print debug info and raise
    print("[ERROR] Could not parse JSON after cleaning.")
    print("=== Response Text Start ===")
    print(cleaned[:500])
    print("=== Response Text End ===")
    raise ValueError("Failed to parse model response as JSON.")

def truncate_to_last_period(text: str) -> str:
    """
    Truncates the given string up to and including the last period.
    If no period is found, returns the original string.
    
    Args:
        text (str): The input string to truncate.

    Returns:
        str: The truncated string or the original string if no period is found.
    """
    last_period_index = text.rfind('.')
    if last_period_index == -1:
        # No period found, return the entire string.
        return text
    # Return the substring up to (and including) the last period.
    return text[:last_period_index + 1]


def attempt_json_repair(bad_json_string):
    """
    Attempts to repair a broken or incomplete JSON string.
    Tries to close braces and brackets intelligently.
    """

    # First: Try naive parse
    try:
        return safe_json_loads(bad_json_string)
    except json.JSONDecodeError:
        pass

    # Step 1: Trim weird trailing junk (like half-words)
    cleaned = re.sub(r'[^\}\]\"]+$', '', bad_json_string.strip())

    # Step 2: Count opening/closing brackets and braces
    open_braces = cleaned.count('{')
    close_braces = cleaned.count('}')
    open_brackets = cleaned.count('[')
    close_brackets = cleaned.count(']')

    # Step 3: Auto-close if needed
    while open_braces > close_braces:
        cleaned += '}'
        close_braces += 1
    while open_brackets > close_brackets:
        cleaned += ']'
        close_brackets += 1

    # Step 4: Try parsing again
    try:
        return safe_json_loads(cleaned)
    except json.JSONDecodeError as e:
        # If still broken, log error
        raise ValueError(f"Failed to repair JSON. Original Error: {str(e)}")

# ─── JSON-escape handling ───────────────────────────────────────────
_ESCAPE_RE = re.compile(r'\\(["\\/bfnrt]|u[0-9a-fA-F]{4})')

def _unescape(match: re.Match) -> str:
    tok = match.group(1)
    if tok.startswith("u"):                 # \uXXXX
        return chr(int(tok[1:], 16))
    return bytes(f"\\{tok}", "utf-8").decode("unicode_escape")

# ─── cleaning helpers ───────────────────────────────────────────────
_NON_ALNUM_OR_DASH = re.compile(r"[^A-Za-z0-9\-]+")     # drop everything but A-Z 0-9 -
_EDGE_DASH         = re.compile(r"(^-|-$)|(?:\s-|-\s)") # remove dashes at edges

def _clean_and_split(token: str, *, alnum_only: bool, lower: bool) -> list[str]:
    """Return a list of final tokens after cleaning."""
    if lower:
        token = token.lower()

    if alnum_only:
        # Strip diacritics → ASCII
        token = (
            unicodedata.normalize("NFKD", token)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
        token = _NON_ALNUM_OR_DASH.sub(" ", token)  # punctuation → space
        token = _EDGE_DASH.sub(" ", token)          # edge-dashes → space
        token = re.sub(r"\s{2,}", " ", token).strip()

    # finally split on whitespace so trailing commas / periods vanish
    return token.split()

# ─── main generator ─────────────────────────────────────────────────
def tokenize_json(text: str,
                  *,
                  strings_only: bool = False,
                  bare_strings : bool = False,
                  alnum_only   : bool = False,
                  lower        : bool = False):
    """
    Yield JSON tokens sequentially.

    bare_strings=True → unescaped, cleaned, and (optionally) split-cleaned tokens.
    """
    if bare_strings:
        strings_only = True

    i, n = 0, len(text)

    while i < n:
        ch = text[i]

        # whitespace --------------------------------------------------
        if ch in " \t\r\n":
            i += 1
            continue

        # punctuation -------------------------------------------------
        if ch in "{}[]:,":
            if not strings_only:
                yield ch
            i += 1
            continue

        # string literal ---------------------------------------------
        if ch == '"':
            i += 1
            buf = []
            while i < n:
                c = text[i]
                if c == "\\":                       # escape + next
                    buf.extend(text[i:i+2])
                    i += 2
                elif c == '"':                      # closing quote
                    raw = "".join(buf)

                    if bare_strings:
                        unesc = _ESCAPE_RE.sub(_unescape, raw)
                        unesc = unesc.replace("\n", " ").replace("\r", " ")
                        for sub in _clean_and_split(unesc,
                                                    alnum_only=alnum_only,
                                                    lower=lower):
                            if sub:
                                yield sub
                    else:
                        yield '"' + raw + '"'
                    i += 1
                    break
                else:
                    buf.append(c)
                    i += 1
            continue

        # number -----------------------------------------------------
        if ch == "-" or ch.isdigit():
            start = i
            i += 1
            while i < n and (text[i].isdigit() or text[i] in ".eE+-"):
                i += 1
            if not strings_only:
                yield text[start:i]
            continue

        # true / false / null ----------------------------------------
        if ch.isalpha():
            start = i
            i += 1
            while i < n and text[i].isalpha():
                i += 1
            if not strings_only:
                yield text[start:i]
            continue

        # fallback ---------------------------------------------------
        if not strings_only:
            yield ch
        i += 1

# utils/parsing.py  (add near the bottom)


def _strip_outer_quotes_once(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        inner = s[1:-1]
        # Only strip if the inner is valid JSON (or can be repaired)
        try:
            json.loads(inner)
            return inner
        except Exception:
            pass
    return s

def normalize_directive_tokens(tokens: list[str]) -> list[str]:
    """
    Normalize whatever came after --directive into exactly ONE JSON token.

    Steps (one pass intent):
      • drop leading '--directive'/'-d' if present
      • join tokens → strip code fences → strip outer quotes once
      • extract first {...} object, parse/repair
      • re-dump compact to guarantee single argv token
    """
    if not tokens:
        return []

    # 1) excise a stray leading flag
    if tokens and tokens[0] in ("--directive", "-d"):
        tokens = tokens[1:]

    joined = " ".join(tokens).strip()

    # 2) optional fence removal (if you ever feed fenced code)
    if joined.startswith("```"):
        joined = re.sub(r"^```[^\n]*\n", "", joined)
        joined = re.sub(r"\n```$", "", joined)

    # 3) strip one layer of outer quotes
    joined = _strip_outer_quotes_once(joined)

    # If nothing left, return empty
    if not joined:
        return []

    # Helper: does it *look* like JSON we should attempt to parse?
    def _looks_like_json(s: str) -> bool:
        s = s.lstrip()
        if not s:
            return False
        # starts with { ... } or [ ... ] or a quoted JSON string
        return s[0] in "{[\""  # double-quote allows JSON string

    # 4) If it doesn't look like JSON at all, treat the whole thing as a JSON string.
    #    This guarantees exactly one argv token and avoids exceptions.
    if not _looks_like_json(joined):
        return [json.dumps(joined, ensure_ascii=False)]

    # 5) Try to extract first JSON-looking object if prose surrounds it
    m = re.search(r"\{.*\}|\[.*\]|^\".*\"$", joined, flags=re.DOTALL)
    json_str = m.group(0) if m else joined

    # 6) parse / repair using your helpers, but never raise — fallback to string
    try:
        obj = safe_json_loads(json_str)
    except Exception:
        try:
            obj = attempt_json_repair(json_str)
        except Exception:
            # Last resort: pass the directive as a JSON string token
            return [json.dumps(joined, ensure_ascii=False)]

    # 7) compact dump → single argv token
    one_token = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return [one_token]