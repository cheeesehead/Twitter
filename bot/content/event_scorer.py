from bot.sports.base import SportEvent

# Base scores by event type
BASE_SCORES = {
    "upset": 8,
    "cinderella": 9,
    "close_game": 7,
    "buzzer_beater": 10,
    "blowout": 5,
    "big_run": 6,
    "crunch_time": 7,
    "halftime": 4,
    "overtime": 8,
    "final": 4,
}

# Philly teams — always tweet about these
PHILLY_TEAMS = {
    # NBA
    "philadelphia 76ers", "76ers", "sixers",
    # NFL
    "philadelphia eagles", "eagles",
    # MLB
    "philadelphia phillies", "phillies",
    # NHL
    "philadelphia flyers", "flyers",
    # MLS
    "philadelphia union", "union",
    # College
    "villanova wildcats", "villanova",
    "temple owls", "temple",
    "drexel dragons", "drexel",
    "saint joseph's hawks", "st. joseph's", "saint joseph's",
    "penn quakers", "penn",
    "la salle explorers", "la salle",
}

# Philly rivals — we love when they lose
PHILLY_RIVALS = {
    "dallas cowboys", "cowboys",
    "dallas mavericks", "mavericks",
    "new york giants", "giants",
    "new york knicks", "knicks",
    "new york mets", "mets",
    "new york yankees", "yankees",
    "new york rangers", "rangers",
    "new york jets", "jets",
    "boston celtics", "celtics",
    "boston red sox", "red sox",
    "washington commanders", "commanders",
    "pittsburgh steelers", "steelers",
    "pittsburgh penguins", "penguins",
}


def _is_philly_involved(data: dict) -> bool:
    teams = [
        data.get("home_team", "").lower(),
        data.get("away_team", "").lower(),
        data.get("winner", "").lower(),
        data.get("loser", "").lower(),
    ]
    return any(t in PHILLY_TEAMS for t in teams if t)


def _is_rival_involved(data: dict) -> bool:
    teams = [
        data.get("home_team", "").lower(),
        data.get("away_team", "").lower(),
        data.get("winner", "").lower(),
        data.get("loser", "").lower(),
    ]
    return any(t in PHILLY_RIVALS for t in teams if t)


def score_event(event: SportEvent) -> float:
    base = BASE_SCORES.get(event.event_type, 5)
    score = float(base)
    data = event.data

    # PHILLY BOOST: always tweet about our teams
    if _is_philly_involved(data):
        score += 3

    # Rival boost: we enjoy covering their losses
    if _is_rival_involved(data):
        score += 1.5

    # Upset magnitude bonus
    if event.event_type == "upset":
        seed_diff = data.get("seed_diff", 0)
        if seed_diff >= 10:
            score += 2
        elif seed_diff >= 7:
            score += 1

    # Cinderella seed bonus (higher seed = more remarkable)
    if event.event_type == "cinderella":
        seed = data.get("cinderella_seed", 12)
        if seed >= 15:
            score += 1.5
        elif seed >= 14:
            score += 1

    # Close game tightness bonus
    if event.event_type in ("close_game", "crunch_time"):
        margin = data.get("margin", 5)
        if margin <= 1:
            score += 1.5
        elif margin <= 2:
            score += 0.5

    # Big run magnitude
    if event.event_type == "big_run":
        swing = data.get("swing", 10)
        if swing >= 15:
            score += 1.5
        elif swing >= 12:
            score += 0.5

    # March Madness boost (tournament games inherently more interesting)
    if data.get("sport") == "March Madness":
        score += 1

    return min(score, 10.0)


def filter_events(events: list[SportEvent], threshold: float = 6.0) -> list[SportEvent]:
    scored = []
    for event in events:
        event.score = score_event(event)
        if event.score >= threshold:
            scored.append(event)
    scored.sort(key=lambda e: e.score, reverse=True)
    return scored
