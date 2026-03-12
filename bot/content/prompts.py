SYSTEM_PROMPT = """You are a witty, engaging sports Twitter personality. You write tweets about live sporting events.

Rules:
- MUST be under 280 characters (this is critical — Twitter will reject longer tweets)
- Use a casual, energetic voice — like a knowledgeable fan, not a news anchor
- Include relevant hashtags when natural (1-2 max)
- NO emojis unless they genuinely add to the tweet
- Be opinionated — hot takes get engagement
- Reference specific scores, seeds, or stats from the data provided
- Don't start tweets with "BREAKING:" or "Just in:" — be more creative
- Vary your style: sometimes a one-liner, sometimes a stat + take, sometimes pure reaction
- Never use the phrase "let that sink in" or "read that again"
"""

CONTENT_TEMPLATES = {
    "upset": """The event: A major upset just happened in {sport}.
{description}

Context: #{winner_seed} seed {winner} beat #{loser_seed} seed {loser}. Seed difference: {seed_diff}.
Score: {home_team} {home_score} - {away_team} {away_score}

Write 2 tweet options reacting to this upset. Make them feel electric.""",

    "cinderella": """The event: A Cinderella story is unfolding in {sport}!
{description}

A #{cinderella_seed} seed just won. That's a huge deal.
Score: {home_team} {home_score} - {away_team} {away_score}

Write 2 tweet options celebrating this underdog moment.""",

    "close_game": """The event: An incredibly close game just finished in {sport}.
{description}

Final: {home_team} {home_score} - {away_team} {away_score} (margin: {margin})

Write 2 tweet options capturing the drama of this finish.""",

    "blowout": """The event: A total blowout in {sport}.
{description}

Final: {home_team} {home_score} - {away_team} {away_score} (margin: {margin})

Write 2 tweet options — can be funny, snarky, or impressed.""",

    "big_run": """The event: A massive scoring run is happening LIVE in {sport}!
{description}

{runner} just went on a {swing}-point swing.
Current score: {home_team} {home_score} - {away_team} {away_score} ({situation})

Write 2 tweet options with live-game energy.""",

    "crunch_time": """The event: Crunch time in a close {sport} game!
{description}

Score: {home_team} {home_score} - {away_team} {away_score} with {time_remaining} left

Write 2 tweet options building hype for this finish.""",

    "overtime": """The event: A game just went to overtime (or ended in OT) in {sport}!
{description}

Score: {home_team} {home_score} - {away_team} {away_score}

Write 2 tweet options about this OT drama.""",

    "halftime": """The event: Halftime update in {sport}.
{description}

Halftime: {home_team} {home_score} - {away_team} {away_score}
Leader: {halftime_leader}

Write 2 tweet options for a halftime take — could be analysis, prediction, or observation.""",

    "final": """A {sport} game just ended.
{description}

Final: {home_team} {home_score} - {away_team} {away_score}

Write 2 tweet options — keep it interesting even if it's a standard result.""",
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

Write 2 tweet options reacting to this."""
