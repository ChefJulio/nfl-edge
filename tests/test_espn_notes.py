"""(EE) nfledge/espn_notes.classify: the phrasing ESPN's notes use, and the traps (negation, hypotheticals, other games)."""
import pytest

from nfledge.espn_notes import classify

CASES = [
  # will play
  ("Jones (ankle) is expected to play Sunday against the Bears, Ian Rapoport of NFL Network reports.", "IN"),
  ("Jones is expected to suit up Sunday.", "IN"),
  ("Coach Kevin O'Connell said Jones will play Sunday.", "IN"),
  ("Jones (hamstring) is on track to play Sunday, per Adam Schefter.", "IN"),
  ("Jones is trending toward playing Sunday.", "IN"),
  ("The Vikings expect Jones to play Sunday.", "IN"),
  ("O'Connell expects to have Jones available Sunday.", "IN"),
  ("Jones is good to go for Sunday's game.", "IN"),
  ("Jones, who did not practice Wednesday, is expected to play Sunday.", "IN"),
  ("Jones didn't practice all week but is expected to play Sunday.", "IN"),
  ("Jones won't miss Sunday's game, per the team.", "IN"),
  ("Jones isn't expected to miss any time.", "IN"),
  ("Jones is not expected to sit out Sunday.", "IN"),
  ("Jones is expected to return Sunday from a two-game absence.", "IN"),
  ("Jones is slated to make his return Sunday.", "IN"),
  ("Jones is expected to play but could be on a snap count.", "IN"),
  ("Jones’s expected to play Sunday.", "IN"),
  ("The team is optimistic Jones will be available Sunday.", "IN"),
  ("Jones is cleared to play Sunday.", "IN"),
  ("Jones has no restrictions heading into Sunday.", "IN"),
  # won't play
  ("Jones isn't expected to play Sunday against Detroit.", "OUT"),
  ("Jones is not expected to play Sunday.", "OUT"),
  ("Jones is no longer expected to play Sunday.", "OUT"),
  ("Jones won't play Sunday.", "OUT"),
  ("Jones will not play Sunday.", "OUT"),
  ("Jones is unlikely to play Sunday.", "OUT"),
  ("Jones is doubtful to play Sunday.", "OUT"),
  ("Jones doesn't plan to play Sunday.", "OUT"),
  ("The Vikings don't expect Jones to play Sunday.", "OUT"),
  ("O'Connell doesn't expect to have Jones Sunday.", "OUT"),
  ("Jones is not on track to play Sunday.", "OUT"),
  ("Jones isn't trending toward playing Sunday.", "OUT"),
  ("Jones is trending toward sitting out Sunday.", "OUT"),
  ("Jones is trending toward not playing Sunday.", "OUT"),
  ("Jones is expected to miss Sunday's game.", "OUT"),
  ("Jones will miss Sunday's game.", "OUT"),
  ("Jones will be held out Sunday.", "OUT"),
  ("Jones has been ruled out for Sunday.", "OUT"),
  ("Jones was downgraded to out Saturday.", "OUT"),
  ("Jones is expected to not play Sunday.", "OUT"),
  ("Jones isn't expected to suit up Sunday.", "OUT"),
  ("Jones isn't currently expected to play Sunday.", "OUT"),
  ("The team isn't optimistic Jones will be available Sunday.", "OUT"),
  ("The team is pessimistic about Jones' chances for Sunday.", "OUT"),
  ("Jones can't go Sunday, O'Connell said.", "OUT"),
  ("Jones is out for Sunday's game.", "OUT"),
  ("Jones is not good to go Sunday.", "OUT"),
  # undecided
  ("Jones is a game-time decision Sunday.", "GTD"),
  ("Jones will be a gametime decision for Sunday.", "GTD"),
  ("Jones is expected to be a game time decision.", "GTD"),
  ("Jones will test his ankle in pregame warmups before a final decision.", "GTD"),
  ("Jones hopes to play Sunday.", "GTD"),
  ("Jones could play Sunday.", "GTD"),
  ("Jones hasn't been ruled out for Sunday.", "GTD"),
  ("Jones' status for Sunday is up in the air.", "GTD"),
  ("Jones could miss Sunday's game.", "GTD"),
  # the news leads: background and hypotheticals don't count
  ("Jones is expected to play Sunday. He was a game-time decision last week before sitting out.", "IN"),
  ("Jones won't play Sunday. Smith is expected to play a larger role in his absence.", "OUT"),
  ("If Jones can't go Sunday, Smith would start.", "NONE"),
  ("Jones is expected to play, but if he can't go, Smith will start.", "IN"),
  ("Jones missed last week's game.", "NONE"),
  ("Jones (knee) was limited at practice Friday and is listed as questionable.", "NONE"),
  ("Jones (ankle) practiced in full Friday.", "NONE"),
  ("Jones will go through pregame warmups.", "GTD"),
  ("Jones is out of his walking boot and is expected to play.", "IN"),
  ("", "NONE"),
]


@pytest.mark.parametrize("note,want", CASES)
def test_classify(note, want):
  assert classify(note) == want


# real notes from the archive (2026 weeks 5-8) that a first version misread
REAL = [
  ("Odeyingbo (quadriceps) is doubtful to return to Sunday's game against the Packers.", "NONE"),
  ("Edwards (hamstring) has been ruled out for the remainder of Sunday's game against the Packers.", "NONE"),
  ("Doubs (shoulder) has been ruled out for the rest of Sunday's game against the Jets, Doug Kyed of the Boston Herald reports.", "NONE"),
  ("The left knee injury that forced Jones out of Sunday's 16-10 win over the Colts isn't considered significant, and the running back is viewed as day-to-day, Adam Schefter of ESPN reports.", "GTD"),
  ('Head coach Mike LaFleur stated he\'s "not too sure" if Reiman (ankle) will play this season, Dani Sureck of the Cardinals\' official site reports.', "GTD"),
  ("Jones (left knee) is expected to play Sunday.", "IN"),
  ("Couch suffered a hamstring injury Sunday versus New England and is doubtful to return.", "NONE"),
  ("Matiscik (shoulder) will not return to Sunday's game against the Eagles in London.", "NONE"),
  ("Kmet exited Thursday night's game against the Patriots with a right knee injury and will not return.", "NONE"),
  ("Kinlaw (knee) won't return to Washington's matchup versus the 49ers on Monday, John Keim of ESPN reports.", "NONE"),
  ("Falcons head coach Kevin Stefanski said that Penix (ribs) will practice Wednesday but will be limited in some fashion, Marc Raimondi of ESPN.com reports.", "NONE"),
  ("Pitre will not need surgery and will not need to be placed on injured reserve as a result of the shoulder injury he suffered during Sunday's game at Tennessee, Aaron Wilson of KPRC 2 Houston reports.", "NONE"),
  ("Giants general manager Joe Schoen said Tuesday that Tracy (hamstring) is slated to be placed on injured reserve, Dan Duggan of The Athletic reports.", "OUT"),
  ('Head coach Dan Campbell confirmed Monday that White (forearm) will need surgery but is expected to return "at some point" later this season, Richard Silva of The Detroit News reports.', "NONE"),
  ('Rice (hamstring) is believed to have sustained a "relatively minor" injury in Sunday\'s win over the Raiders and could be ready to play following the Chiefs\' Week 5 bye, Ian Rapoport of NFL Network reports.', "NONE"),
  ("Head coach Nick Sirianni expressed hope Monday that Smith (hamstring) will return for this Sunday's game against the Panthers, Zach Berman of The Athletic reports.", "GTD"),
  ('Head coach Nick Sirianni said Monday that he\'s "hopeful" that both Barkley (hamstring) and DeVonta Smith (hamstring) will both be cleared to play against the Panthers this coming Sunday, Zach Berman of The Athletic reports.', "GTD"),
  ("Jets head coach Aaron Glenn said that Hall (quadriceps) won't practice Wednesday but hasn't been ruled out from playing Sunday versus the Dolphins, Al Iannazzone of Newsday reports.", "GTD"),
  ("Zaccheaus (shoulder) is trending toward not being available for Sunday's game against the 49ers, Ian Rapoport of NFL Network reports.", "OUT"),
  ("Hall (quadriceps) is unlikely to suit up for Sunday's game against the Dolphins, Ian Rapoport of NFL Network reports.", "OUT"),
  ("Coach Mike Vrabel said Tuesday that Brown (knee) probably won't be available for Thursday's game against the Bears, Mike Reiss of ESPN.com reports.", "OUT"),
  ("Henderson (ankle), who is listed as questionable for Sunday's game against the Jets, is likely to suit up, Ian Rapoport of NFL Network reports.", "IN"),
  ("Sadiq (concussion) is in line to be available for Sunday's game at New England, Ian Rapoport of NFL Network reports.", "IN"),
  ("Barton is battling through an illness but is expected to be active for Sunday's game against the Falcons, Scott Smith of the Buccaneers' official site reports.", "IN"),
  ("Williams (hamstring) is expected to start Sunday's game against the Falcons, Adam Schefter of ESPN reports.", "IN"),
  ("Vorhees (foot) is inactive for Sunday night's matchup with Atlanta.", "OUT"),
  ("Henderson (illness) has been downgraded from questionable to out for Sunday's game against the Dolphins, Ian Rapoport of ESPN and NFL Network reports.", "OUT"),
  ("Tate (shoulder) won't practice Friday, and his status for Sunday's game against the Bengals is in doubt, Paul Kuharsky reports.", "GTD"),
  ('Henderson said Friday that an MRI revealed he sustained a high-ankle sprain but that he is "hoping to play" Sunday against the Jets, Doug Kyed of the Boston Herald reports.', "GTD"),
]


@pytest.mark.parametrize("note,want", REAL)
def test_real(note, want):
  assert classify(note) == want
