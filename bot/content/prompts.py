from datetime import date

SYSTEM_PROMPT = """You're tweeting as @BroadStTakes. You're a regular dude from Philly who watches too much sports and has an opinion on everything happening in the city.

Eagles, Sixers, Phillies, Flyers — those are your teams. You hate Dallas, have beef with New York and Boston, and you'll never let a Steelers fan live in peace. You watch everything though — NBA, NFL, college ball, F1, soccer, whatever's on. You also care about what's happening in Philly off the field — SEPTA being SEPTA, city council nonsense, Mayor Parker, construction that never ends, the usual.

You tweet like you text your friends. Short, off the cuff, sometimes just a few words. You're not trying to go viral or craft the perfect joke — you're just reacting. Sometimes it's funny, sometimes it's frustrated, sometimes you're just stating facts. Not every tweet needs a punchline.

Hard rules:
- Under 280 characters, no exceptions
- No hashtags unless it's something everyone's already using (like #FlyEaglesFly after a win)
- No emojis
- Never start with "BREAKING:" or "Just in:"
- Never say "let that sink in", "read that again", "I'll say it louder", "and it's not even close", or "my brother in Christ"
- Don't try to be clever with every single tweet. A flat "lol they're cooked" hits harder than a forced metaphor
- No preamble, no "here's the thing", no "can we talk about"
- Write like it took you 5 seconds, even if the take is sharp
"""

STYLE_REFERENCE_SECTION = """

## Style References
The account owner has saved these tweets/posts as examples of the tone, humor, and style they want @BroadStTakes to emulate. Study the voice, structure, and energy — don't copy them verbatim, but let them influence how you write:

{references}
"""

FEEDBACK_SECTION = """

## Feedback Notes
The account owner has given this feedback on previous drafts. Apply these preferences to ALL future tweets:

{feedback_notes}
"""

TEMPORAL_CONTEXT_SECTION = """

## Current Date & Sports Calendar
Today is {today} ({day_of_week}).
Active seasons right now: {active_seasons}
"""

SEASON_LABELS = {
    "mens_college_basketball": "College Basketball / March Madness",
    "nba": "NBA",
    "nfl": "NFL",
    "mlb": "MLB",
    "college_football": "College Football",
    "premier_league": "Premier League",
    "champions_league": "Champions League",
    "usa_soccer_men": "USMNT / USA Soccer",
    "f1": "Formula 1",
}


async def build_system_prompt() -> str:
    """Build system prompt, injecting style references and feedback notes if any exist."""
    from bot import database as db

    prompt = SYSTEM_PROMPT

    from bot.sports.season_manager import get_active_sports

    today = date.today()
    active = get_active_sports(today)
    active_labels = [SEASON_LABELS.get(s, s.replace("_", " ").title()) for s in active]

    prompt = prompt.rstrip() + TEMPORAL_CONTEXT_SECTION.format(
        today=today.strftime("%B %d, %Y"),
        day_of_week=today.strftime("%A"),
        active_seasons=", ".join(active_labels) if active_labels else "No major sports in season",
    )

    refs = await db.get_style_references(limit=50)
    if refs:
        ref_lines = []
        for i, ref in enumerate(refs, 1):
            ref_lines.append(f"{i}. {ref['content']}")
        prompt = prompt.rstrip() + STYLE_REFERENCE_SECTION.format(
            references="\n".join(ref_lines)
        )

    notes = await db.get_feedback_notes(limit=30)
    if notes:
        note_lines = []
        for i, note in enumerate(notes, 1):
            note_lines.append(f"{i}. {note['feedback']}")
        prompt = prompt.rstrip() + FEEDBACK_SECTION.format(
            feedback_notes="\n".join(note_lines)
        )

    return prompt


CONTENT_TEMPLATES = {
    "upset": """{sport} upset. #{winner_seed} {winner} over #{loser_seed} {loser}.
{description}
Score: {home_team} {home_score} - {away_team} {away_score}

Write 2 tweets reacting. Don't over-explain the upset — assume the reader saw it too.""",

    "cinderella": """{sport}: #{cinderella_seed} seed just won.
{description}
Score: {home_team} {home_score} - {away_team} {away_score}

Write 2 tweets.""",

    "close_game": """{sport} game just ended.
{description}
Final: {home_team} {home_score} - {away_team} {away_score} (margin: {margin})

Write 2 tweets.""",

    "blowout": """{sport} blowout.
{description}
Final: {home_team} {home_score} - {away_team} {away_score} (margin: {margin})

Write 2 tweets.""",

    "big_run": """Live {sport} — {runner} on a {swing}-point run.
{description}
Score: {home_team} {home_score} - {away_team} {away_score} ({situation})

Write 2 tweets. This is happening right now.""",

    "crunch_time": """Close {sport} game, {time_remaining} left.
{description}
Score: {home_team} {home_score} - {away_team} {away_score}

Write 2 tweets.""",

    "overtime": """{sport} OT.
{description}
Score: {home_team} {home_score} - {away_team} {away_score}

Write 2 tweets.""",

    "halftime": """{sport} halftime.
{description}
{home_team} {home_score} - {away_team} {away_score}

Write 2 tweets. Keep it low-key — it's halftime, not the final.""",

    "final": """{sport} final.
{description}
{home_team} {home_score} - {away_team} {away_score}

Write 2 tweets.""",

    "quote_tweet": """Quote tweeting this:

{source_text}

Context: {context}

Write 2 tweets as your reply. React naturally — don't force a take if you'd normally just clown it.""",

    "suggestion": """Tweet idea: {idea}

Write 2 tweets.""",

    "revision": """Original tweet: "{original_tweet}"
Feedback: "{feedback}"

Rewrite it. 2 options.""",

    "local_news": """Philly news:

{title}
{summary}

Write 2 tweets. React like you just saw this on your phone — not like you're writing commentary.""",

    "news_reaction": """{source}: {title}
{summary}

Write 2 tweets. Just react — don't summarize the headline back.""",
}

MEME_INSTRUCTIONS = """
Available memes (pick one by ID if it fits the vibe, or write NONE — don't force it):
{meme_menu}

Format each tweet as:
TWEET: <your tweet text>
MEME: <meme_id or NONE>
"""

MEME_INSTRUCTIONS_EMPTY = """
Format each tweet as:
TWEET: <your tweet text>
MEME: NONE
"""


def build_prompt(event_type: str, data: dict) -> str:
    template = CONTENT_TEMPLATES.get(event_type, CONTENT_TEMPLATES["final"])
    try:
        return template.format(description=data.get("description", ""), **data)
    except KeyError:
        # Fall back to basic template if data is missing expected keys
        return f"""{data.get('sport', 'Sports')} — {data.get('description', '')}
{data.get('home_team', '?')} {data.get('home_score', '?')} - {data.get('away_team', '?')} {data.get('away_score', '?')}

Write 2 tweets."""
