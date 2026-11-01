"""(EE) ESPN's injury notes read for the game-day call: OUT (won't play), GTD (game-time decision), IN (will play),
NONE (nothing about this game).

Negation-aware (owner 2026-11-01: "isn't expected to play" is a lot different from "is expected to play"):
- the text is lowercased and contractions expanded ("won't" -> "will not", "doesn't" -> "does not"; "no longer" /
  "never" -> "not", "unlikely" -> "not likely", "pessimistic" -> "not optimistic");
- split into sentences, then clauses ("but", "although", ";", " - "); hypothetical clauses ("if he can not go, ...")
  and other games ("last week", "next week") are dropped;
- a play phrase ("expected to play", "expects him to play", "will suit up", "on track to return", "good to go") is IN,
  or OUT when a "not" governs it: right before it with only helper words between ("is not expected", "does not
  expect", "will not") or inside it ("expected to not play"). A sit phrase ("expected to miss", "will be held out")
  is the reverse. "did not practice, is expected to play" stays IN: "practice" isn't a helper word;
- "game-time decision" / "50-50" / "pregame warmups" / "hopes to play" / "could play" are GTD.
The first sentence that says anything decides (the news leads, background follows); inside it OUT > GTD > IN.
Cases: tests/test_espn_notes.py.
"""
import re

_NORM = [(r"won't", "will not"), (r"can't", "can not"), (r"\bcannot\b", "can not"), (r"\bain't\b", "is not"),
         (r"n't\b", " not"), (r"\bno longer\b", "not"), (r"\bnever\b", "not"), (r"\bunlikely\b", "not likely"),
         (r"\bpessimistic\b", "not optimistic"), (r"\bdoubtful to\b", "not likely to"), (r"\bgametime\b", "game-time"),
         (r"\bgame time\b", "game-time"), (r"\bwarm ?ups?\b", "warmups"), (r"\bpre-game\b", "pregame")]
# words that can sit between "not" and the verb it negates ("is not currently expected", "does not yet expect")
HELPER = {"is", "are", "was", "were", "be", "been", "being", "does", "do", "did", "has", "have", "had", "will", "would",
          "should", "could", "can", "may", "might", "he", "it", "'s", "currently", "still", "now", "yet", "officially",
          "reportedly", "apparently", "also", "even", "quite", "as", "seem", "seems", "appear", "appears", "look", "looks",
          "feel", "feels", "sound", "sounds", "considered", "longer", "a", "lock", "sure", "certain", "thought", "believed"}
PLAY = (r"(?:play(?:ing)?\b(?!\s+(?:in\s+)?(?:practice|a practice|the practice))|suit(?:ing)? up|dress\b|be (?:active|available|in the lineup"
        r"|on the field|out there|on a snap count|eased back)|go\b(?!\s+(?:on|to|through|back on|into|down|with)\b)"
        r"|make (?:his|the|a) (?:return|debut)|return(?:ing)?\b(?!\s+to\s+(?:practice|the practice|individual|the walkthrough))"
        r"|have (?:him|\w+)(?:\s+\w+)? (?:back|available|out there|on the field|active)|have (?:him|\w+)\b(?=\s*(?:sunday|monday|thursday|saturday|for|against|this|tonight|$|[,.]))|take the field|give it a go|start\b(?=[\s,.]+(?:sunday|monday|thursday|saturday|against|vs|tonight|this)))")
# a head that says he will / won't: "expected to", "expects him to", "on track to", "will" ...
HEAD = (r"\b(?:(?:expected|anticipated|projected|likely|slated|set|poised|on track|on pace|in line|on course|primed|ready|cleared"
        r"|planning|plans?|intends?|figures?|looks?|appears?|optimistic|confident|going|expects?|expecting|believes?|thinks?"
        r"|anticipates?|trending (?:toward|towards|to)|in position|able|hopes?|hoping|hopeful|chance)"
        r"(?:\s+(?:that\s+)?(?:\w+\s+){0,2}?(?:will|would|is going to|to))?|will|should|would|is going to|can|could|may|might)")
WILL = re.compile(rf"(?P<head>{HEAD})\s+(?P<mid>(?:\w+\s+){{0,3}}?)(?:be able to\s+)?(?P<play>{PLAY})")
SIT = (r"(?:miss(?:ing)?\b|sit(?:ting)?\b(?!\s+(?:down|in))|be (?:inactive|sidelined|held out|out\b(?!\s+(?:there|of))|ruled out|unavailable"
       r"|a healthy scratch|scratched|shut down)|remain (?:out|sidelined)|sit (?:this one )?out)")
SITS = re.compile(rf"(?P<head>{HEAD})\s+(?P<mid>(?:\w+\s+){{0,3}}?){SIT}")
# already ruled: out unless negated right before ("has not been ruled out" = undecided)
RULED = re.compile(r"\b(?:ruled out|downgraded to out|declared out|will be out\b(?!\s+there)|is out (?:for|against|sunday|monday|thursday|saturday|this|tonight)"
                   r"|is inactive|listed as inactive|on the inactive list|among (?:the|his team's|\w+'s) inactives"
                   r"|out for (?:sunday|monday|thursday|saturday|the game|week|the contest|this week)|no chance|shut down|doubts? (?:that )?\w+ (?:will|can|is going to))")
TREND_OUT = re.compile(r"\btrending (?:toward|towards|to) (?:not playing|sitting|missing|being inactive|being out|not\b|a (?:missed|absence))")
GTD = re.compile(r"\bgame-time (?:decision|call|choice)\b|\btrue gtd\b|\b50-50\b|\bcoin flip\b|\bup in the air\b|\btouch[- ]and[- ]go\b"
                 r"|\bpregame warmups\b|\bfinal decision\b|\btest (?:it|his \w+|the \w+)(?: out)? (?:before|during|in)\b"
                 r"|\bwait and see\b|\bday-to-day\b|\buncertain\b|\bremains? questionable\b|\bin doubt\b|\btoo early to (?:say|tell)\b"
                 r"|\bnot (?:too |so |entirely |quite |yet )?sure\b|\bunsure\b|\bunclear\b|\bremains to be seen\b")
POS = re.compile(r"\b(?:good to go|a go\b|cleared to (?:play|return)|full go|(?:positive|right|good) direction|no restrictions|without restrictions"
                 r"|no limitations|be fine\b|be ready\b)")
# placed on IR: out ("will not need to be placed on ir": nothing)
IR = re.compile(r"\b(?:placed|moved|land|go) on (?:injured reserve|ir)\b|\bto ir\b")
# the game he got hurt in, not the next one: "ruled out for the remainder of sunday's game", "will not return to
# sunday's game", "doubtful to return", "exited ... and will not return". Wins over the ruled-out phrases.
INGAME = re.compile(r"\b(?:remainder|rest) of (?:[\w'.-]+ ){0,4}?(?:game|contest|matchup|tilt|clash)\b"
                    r"|\breturn(?:ing)? to (?:[\w'.-]+ ){0,5}?(?:game|matchup|contest|clash|tilt|showdown|meeting)\b"
                    r"|\b(?:likely|questionable|expected|probable) to return$|\bnot return$"
                    r"|\b(?:exited|left the game|departed|was carted|forced (?:him )?out)\b")
# weeks away, not this game ("expected to return at some point later this season", "following the bye")
HORIZON = re.compile(r"\bat some point\b|\blater (?:this|in the) season\b|\bdown the (?:road|stretch)\b|\bin the coming weeks\b|\beventually\b"
                     r"|\bbye\b|\bnext month\b|\bweeks? from now\b")
# "expressed hope that he will return sunday": hoped for, not said
HOPED = re.compile(r"\bhop(?:e|es|ed|eful|ing)\b")
HOPE = re.compile(r"^(?:hopes?|hoping|hopeful|could|may|might|chance)")
HYPO = re.compile(r"^(?:and |but |so |though |although )?(?:if|should|unless|in the event|in case|were|assuming|whether|even if|when and if|otherwise)\b")
OTHER_GAME = re.compile(r"\b(?:last|previous|prior) (?:week|game|weekend|sunday|monday|thursday|outing|contest|season|year)\b|\bnext week\b"
                        r"|\ba week ago\b|\bweek \d+\b|\bbefore the bye\b|\bin (?:his|the) (?:last|previous) \w+\b|\blast time\b")
THIS_GAME = re.compile(r"\b(?:this week|this weekend|sunday|monday|thursday|saturday|tonight|today|this game|against|vs)\b")
_ABBR = re.compile(r"\b(?:jr|sr|st|mr|vs|no|[a-z])\.$")


def _norm(text: str) -> str:
  t = str(text or "").lower().replace("\u2019", "'").replace("\u2018", "'").replace("\u2013", "-").replace("\u2014", " - ")
  for a, b in _NORM:
    t = re.sub(a, b, t)
  return re.sub(r"\s+", " ", t).strip()


def _sentences(t: str) -> list:
  parts, cur = [], ""
  for s in re.split(r"(?<=[.!?])\s+", t):
    cur = f"{cur} {s}".strip() if cur else s
    if not _ABBR.search(cur):
      parts.append(cur)
      cur = ""
  return parts + ([cur] if cur else [])


def _clauses(s: str) -> list:
  return [c.strip(" ,.") for c in re.split(r";|,? but |,? although |,? though |,? while |,? however,? |,? whereas | - "
                                           r"|,(?= (?:if|unless|should|otherwise) )|,? and (?=(?:if|unless|should) )", s) if c.strip(" ,.")]


def negated(c: str, start: int, extra: set = frozenset()) -> bool:
  """A "not" governing the word at `start`: right before it, with only helper words between."""
  for w in reversed(c[:start].split()):
    if w.endswith((",", ":", ";")):
      return False  # a clause boundary
    if w == "not":
      return True
    if w not in HELPER and w not in extra:
      return False
  return False


def _clause(c: str) -> str:
  """OUT / GTD / IN / '' for one normalized clause."""
  if HYPO.search(c):
    return ""  # "if he can not go, x will start": a conditional isn't the news
  if OTHER_GAME.search(c) and not THIS_GAME.search(c):
    return ""  # about another game ("he missed last week's game")
  if INGAME.search(c):
    return ""  # the game he got hurt in, not the next one
  if HORIZON.search(c) and not RULED.search(c):
    return ""  # weeks away ("expected to return at some point later this season", "after the bye")
  out = gtd = inn = False
  if TREND_OUT.search(c):
    out = True
  for m in IR.finditer(c):
    out = out or not negated(c, m.start(), extra={"to", "need", "needs", "be"})
  for m in RULED.finditer(c):
    if negated(c, m.start()):
      gtd = True  # "has not been ruled out"
    else:
      out = True
  for m in GTD.finditer(c):
    gtd = gtd or not negated(c, m.start())
  for m in WILL.finditer(c):
    if TREND_OUT.search(c[m.start():m.end() + 12]):
      continue
    neg = negated(c, m.start()) or "not" in m.group("mid").split() or "not" in m.group("head").split()
    if neg:
      out = True
    elif (HOPE.search(m.group("head")) or HOPED.search(c[:m.start()])) and not re.match(r"be (?:limited|on a snap count|eased back)", m.group("play")):
      gtd = True  # "hopes to play", "could play": undecided
    else:
      inn = True
  for m in SITS.finditer(c):
    neg = negated(c, m.start()) or "not" in m.group("mid").split() or "not" in m.group("head").split()
    if HOPE.search(m.group("head")) and not neg:
      gtd = True  # "could miss"
    elif neg:
      inn = True  # "will not miss", "not expected to sit"
    else:
      out = True
  for m in POS.finditer(c):
    if negated(c, m.start()):
      out = True
    else:
      inn = True
  if not (out or inn):
    m = re.search(r"\b(?:optimistic|confident|encouraged|feeling good)\b", c)
    if m:
      out, inn = (True, False) if negated(c, m.start()) else (False, True)
  return "OUT" if out else "GTD" if gtd else "IN" if inn else ""


def classify(text: str) -> str:
  """OUT / GTD / IN / NONE for an ESPN note: the first sentence that says something about this game decides."""
  for s in _sentences(_norm(text)):
    got = [k for k in (_clause(c) for c in _clauses(s)) if k]
    if got:
      return "OUT" if "OUT" in got else "GTD" if "GTD" in got else "IN"
  return "NONE"
