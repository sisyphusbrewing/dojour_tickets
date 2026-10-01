# ---------------------------------------------------------------------------
# BULLETPROOF SHOWTIME PARSER
# ---------------------------------------------------------------------------
WEEKDAYS = {'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun', 
            'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'}

def clean_variant_name(raw_str):
    """Formats and standardizes a single date/time string."""
    s = raw_str.strip().strip(",").strip("•").strip("-")
    # Remove comma directly after weekday: "Fri, Jan 29" -> "Fri Jan 29"
    s = re.sub(r'^(Sun|Mon|Tue|Wed|Thu|Fri|Sat),\s*', r'\1 ', s, flags=re.IGNORECASE)
    return s

def generate_variants(showtimes_raw):
    # 1. Split on pipe (|), semicolon (;), or newline first
    if "|" in showtimes_raw:
        chunks = [c.strip() for c in showtimes_raw.split("|") if c.strip()]
    elif ";" in showtimes_raw:
        chunks = [c.strip() for c in showtimes_raw.split(";") if c.strip()]
    elif "\n" in showtimes_raw:
        chunks = [c.strip() for c in showtimes_raw.split("\n") if c.strip()]
    else:
        # Split on commas
        chunks = [c.strip() for c in showtimes_raw.split(",") if c.strip()]

    # 2. Recombine orphan weekdays (e.g. if 'Fri' got split from 'Jan 29 • 7:00 PM')
    recombined = []
    pending_day = ""

    for chunk in chunks:
        # Check if this chunk is just a weekday name (e.g. "Fri" or "Sat")
        clean_chunk = chunk.strip().lower().rstrip(",")
        if clean_chunk in WEEKDAYS:
            pending_day = chunk.strip().capitalize()
            continue

        if pending_day:
            full_str = f"{pending_day} {chunk.strip()}"
            pending_day = ""
        else:
            full_str = chunk.strip()

        cleaned = clean_variant_name(full_str)
        if cleaned and cleaned.lower() not in WEEKDAYS:
            recombined.append(cleaned)

    # 3. Deduplicate preserving order
    final_variants = []
    seen = set()
    for v in recombined:
        if v not in seen:
            seen.add(v)
            final_variants.append(v)

    if not final_variants:
        final_variants = ["General Admission"]

    return final_variants
