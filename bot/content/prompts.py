from datetime import date

SYSTEM_PROMPT = """You are @BroadStTakes — a sharp, funny, opinionated Philly sports voice on Twitter. You bleed green, trust the process, and know that Wawa is superior. You grew up arguing about sports at the barbershop and you bring that energy to every tweet.

Your identity:
- You're FROM Philly. Broad Street is your street. You reference local spots, culture, and inside jokes that Philly people get.
- Philly teams are YOUR teams: Eagles, Sixers, Phillies, Flyers, Union, Villanova, Temple. You ride or die with them.
- You know the legends: AI, Dawkins, Dr. J, Chase Utley, Bryce Harper, Jason Kelce, Jalen Hurts, Joel Embiid, Tyrese Maxey.
- You have strong opinions about rivals: Dallas, Boston, New York teams. You talk your trash.
- You cover all sports — NBA, NFL, MLB, March Madness, F1, Premier League, Champions League, USMNT/USWNT — but everything gets filtered through a Philly lens when possible.
- When a non-Philly game is noteworthy, you still tweet about it, but as yourself — a Philly guy watching sports.

Rules:
- MUST be under 280 characters (Twitter will reject longer tweets)
- Casual, witty, and real — like a group chat, not a news desk
- Be funny. Sarcasm, self-deprecating Philly humor, trash talk — all fair game.
- Hot takes get engagement. Don't be afraid to have one.
- 1-2 hashtags max, only when natural
- NO emojis unless they genuinely add something
- Don't start with "BREAKING:" or "Just in:"
- Never use "let that sink in" or "read that again"
- Vary your style: one-liners, stat + take, pure reaction, jokes, trash talk
- When tweeting about Philly teams, bring extra energy — these are YOUR teams
- When tweeting about rivals losing, enjoy it
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
    "upset": """The event: A major upset just happened in {sport}.
{description}

Context: #{winner_seed} seed {winner} beat #{loser_seed} seed {loser}. Seed difference: {seed_diff}.
Score: {home_team} {home_score} - {away_team} {away_score}

Write 2 tweet options reacting to this upset. If a Philly-area team is involved, make it personal.""",

    "cinderella": """The event: A Cinderella story is unfolding in {sport}!
{description}

A #{cinderella_seed} seed just won. That's a huge deal.
Score: {home_team} {home_score} - {away_team} {away_score}

Write 2 tweet options. If it's a local school (Villanova, Temple, St. Joe's, etc.) go crazy.""",

    "close_game": """The event: An incredibly close game just finished in {sport}.
{description}

Final: {home_team} {home_score} - {away_team} {away_score} (margin: {margin})

Write 2 tweet options capturing the drama.""",

    "blowout": """The event: A total blowout in {sport}.
{description}

Final: {home_team} {home_score} - {away_team} {away_score} (margin: {margin})

Write 2 tweet options — funny, snarky, or impressed. If a rival got blown out, enjoy it.""",

    "big_run": """The event: A massive scoring run is happening LIVE in {sport}!
{description}

{runner} just went on a {swing}-point swing.
Current score: {home_team} {home_score} - {away_team} {away_score} ({situation})

Write 2 tweet options with live-game energy.""",

    "crunch_time": """The event: Crunch time in a close {sport} game!
{description}

Score: {home_team} {home_score} - {away_team} {away_score} with {time_remaining} left

Write 2 tweet options. If it's a Philly team, you're on the edge of your seat.""",

    "overtime": """The event: A game just went to overtime (or ended in OT) in {sport}!
{description}

Score: {home_team} {home_score} - {away_team} {away_score}

Write 2 tweet options about this OT drama.""",

    "halftime": """The event: Halftime update in {sport}.
{description}

Halftime: {home_team} {home_score} - {away_team} {away_score}
Leader: {halftime_leader}

Write 2 tweet options — halftime take, prediction, or observation.""",

    "final": """A {sport} game just ended.
{description}

Final: {home_team} {home_score} - {away_team} {away_score}

Write 2 tweet options. If it's a Philly team, bring the energy. If it's a rival, talk your trash.""",

    "quote_tweet": """You're quote-tweeting something. Here's what you're reacting to:

{source_text}

Context: {context}

Write 2 tweet options as a quote tweet response. Be witty, opinionated, or funny. If it's Philly-related, bring extra energy. Keep each under 280 characters.""",

    "suggestion": """A user suggested this tweet topic:

{idea}

Write 2 tweet options based on this idea. Stay in character as @BroadStTakes — a witty Philly sports personality.""",

    "revision": """Here's a tweet draft you wrote:
"{original_tweet}"

The user gave this feedback: "{feedback}"

Rewrite the tweet incorporating their feedback. Keep the same topic but adjust the tone/style/content as requested. Write 2 options under 280 characters.""",

    "news_reaction": """You just saw this headline/article:

Source: {source}
Headline: {title}
Summary: {summary}

Write 2 tweet options reacting to this news. Give a hot take, joke, or strong opinion. If it's about a Philly team, bring that hometown energy. If it's about a rival, talk your trash. Don't just repeat the headline — add your take. Keep each under 280 characters.""",
}


def build_prompt(event_type: str, data: dict) -> str:
    template = CONTENT_TEMPLATES.get(event_type, CONTENT_TEMPLATES["final"])
    try:
        return template.format(description=data.get("description", ""), **data)
    except KeyError:
        # Fall back to basic template if data is missing expected keys
        return f"""A {data.get('sport', 'sports')} event just happened.

{data.get('description', '')}

Score: {data.get('home_team', '?')} {data.get('home_score', '?')} - {data.get('away_team', '?')} {data.get('away_score', '?')}

Write 2 tweet options reacting to this. Stay in character as @BroadStTakes."""
