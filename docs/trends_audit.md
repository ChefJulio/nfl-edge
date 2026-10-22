# Trends audit vs nflverse official season totals

Run 2026-10-22 with `tools/trends_audit.py` (drives the live page's CSV export for every season and family, matched on
player ID). Fixes the audit found, all in `tools/trends_build.py`: touchdowns credited only to the scorer (not on a
defensive return or after a lateral), yards split at a lateral, 1999-2000 plays with a blank play type kept, a
scramble-then-throw kept as a pass, any rush / pass attempt counted whatever its label (one mislabeled 2011 run, fixed
after this run: Mark Ingram's 14 yards). Spot checks of the remaining differences (Elliott 2017, Cooper 2015, Gordon
2012, Testaverde 2004, Pittman 2025) found Trends equal to the sum of nflverse's own play-by-play and nflverse's
season table different, i.e. post-game stat corrections that only the season table has.

Seasons 1999-2025, regular season. Kneels / spikes netted out of carries / attempts (see tools/trends_audit.py).

| Family | Stat | Player-seasons | Exact | Within 1 | Official total | Trends total |
|---|---|---|---|---|---|---|
| rush | Rushes | 8,676 | 99.97% | 100.00% | 368,958 | 368,955 |
| rush | Yards | 8,676 | 99.98% | 99.98% | 1,603,034 | 1,602,985 |
| rush | TDs | 8,676 | 99.98% | 100.00% | 11,668 | 11,668 |
| rec | Targets | 10,130 | 99.94% | 100.00% | 360,068 | 360,068 |
| rec | Catches | 10,183 | 99.98% | 100.00% | 232,053 | 232,051 |
| rec | Yards | 10,183 | 99.44% | 99.48% | 2,633,335 | 2,633,380 |
| rec | TDs | 10,183 | 100.00% | 100.00% | 16,189 | 16,189 |
| pass | Attempts | 2,741 | 99.74% | 100.00% | 467,313 | 467,306 |
| pass | Yards | 2,741 | 99.85% | 99.85% | 3,291,438 | 3,291,408 |
| pass | TDs | 2,741 | 100.00% | 100.00% | 20,084 | 20,084 |
| pass | INTs | 2,741 | 100.00% | 100.00% | 12,772 | 12,772 |

Targets not compared where nflverse's season table has fewer targets than catches: 53 player-seasons (2003: 3, 2004: 5, 2006: 15, 2007: 13, 2008: 17).

## Largest differences (83 player-season-stats differ)

| Season | Family | Stat | Player | Trends | Official (adj.) |
|---|---|---|---|---|---|
| 2024 | rush | Yards | Dare Ogunbowale (00-0033854) | 77 | 112 |
| 2017 | rec | Yards | Ezekiel Elliott (00-0033045) | 249 | 269 |
| 2000 | rec | Yards | Plaxico Burress (00-0019642) | 254 | 273 |
| 2000 | pass | Yards | Kordell Stewart (00-0015700) | 1,841 | 1,860 |
| 2024 | rec | Yards | Eric Saubert (00-0033576) | 80 | 97 |
| 2015 | rec | Yards | Richard Rodgers (00-0031384) | 526 | 510 |
| 2011 | rush | Yards | Mark Ingram (00-0027966) | 478 | 492 |
| 2004 | pass | Yards | Vinny Testaverde (00-0016193) | 3,518 | 3,532 |
| 2004 | pass | Yards | Keyshawn Johnson (00-0008561) | 14 | 0 |
| 2013 | rec | Yards | Le'Ron McClain (00-0025524) | 6 | -7 |
| 2015 | rec | Yards | Amari Cooper (00-0031544) | 1,082 | 1,070 |
| 2015 | rec | Yards | Davante Adams (00-0031381) | 495 | 483 |
| 2022 | rec | Yards | Zay Jones (00-0033891) | 834 | 823 |
| 2016 | rec | Yards | Lamar Miller (00-0029615) | 199 | 188 |
| 2005 | pass | Yards | Brett Favre (00-0005106) | 3,881 | 3,892 |
| 2014 | rec | Yards | Markus Wheaton (00-0030460) | 654 | 644 |
| 2002 | rec | Yards | Dennis Northcutt (00-0019650) | 591 | 601 |
| 2025 | rec | Yards | Michael Pittman (00-0036252) | 793 | 784 |
| 2024 | rec | Yards | Josh Palmer (00-0036988) | 575 | 584 |
| 2013 | rec | Yards | Le'Veon Bell (00-0030496) | 408 | 399 |
| 2021 | rec | Yards | Trinity Benson (00-0034930) | 95 | 103 |
| 2018 | rec | Yards | Javorius Allen (00-0031577) | 204 | 196 |
| 2017 | rec | Yards | Giovani Bernard (00-0030456) | 381 | 389 |
| 2013 | rec | Yards | Jason Snelling (00-0025631) | 224 | 216 |
| 2012 | rec | Yards | Josh Gordon (00-0029664) | 797 | 805 |
| 2011 | rec | Yards | Adrian Peterson (00-0025394) | 131 | 139 |
| 2010 | rec | Yards | Roy Williams (00-0022909) | 538 | 530 |
| 2024 | rec | Yards | Gabe Davis (00-0036196) | 246 | 239 |
| 2020 | rec | Yards | Brandin Cooks (00-0031236) | 1,143 | 1,150 |
| 2018 | rec | Yards | Nelson Agholor (00-0031549) | 743 | 736 |
| 2015 | rec | Yards | Antonio Brown (00-0027793) | 1,841 | 1,834 |
| 2013 | rec | Yards | Keenan Allen (00-0030279) | 1,053 | 1,046 |
| 2012 | rec | Yards | Demaryius Thomas (00-0027874) | 1,427 | 1,434 |
| 2024 | rec | Yards | Ladd McConkey (00-0039915) | 1,155 | 1,149 |
| 2022 | rec | Yards | Chase Claypool (00-0036326) | 457 | 451 |
| 2016 | rec | Yards | Tyreek Hill (00-0033040) | 599 | 593 |
| 2013 | rec | Yards | Eddie Royal (00-0026182) | 625 | 631 |
| 2012 | rec | Yards | Greg Little (00-0027997) | 641 | 647 |
| 2024 | rec | Yards | Brandon Aiyuk (00-0036261) | 369 | 374 |
| 2018 | rec | Yards | Nick Foles (00-0029567) | 15 | 10 |

## In one list only (2546)

fam   side         
pass  official only       4
rec   Trends only      2537
      official only       3
rush  official only       2

| Season | Family | Player | Side |
|---|---|---|---|
| 2001 | rush | nan (nan) | official only |
| 2001 | pass | nan (nan) | official only |
| 2002 | rec | Todd Weiner (00-0017399) | Trends only |
| 2003 | rush | nan (nan) | official only |
| 2003 | rec | Dedric Ward (00-0017160) | Trends only |
| 2003 | rec | Travis Taylor (00-0019721) | Trends only |
| 2003 | rec | David Givens (00-0021353) | Trends only |
| 2003 | rec | Jeff Robinson (00-0013872) | Trends only |
| 2003 | rec | Jimmy Redmond (00-0019975) | Trends only |
| 2003 | rec | Marvin Harrison (00-0007024) | Trends only |
| 2003 | rec | James Hodgins (00-0007546) | Trends only |
| 2003 | rec | Ifeanyi Ohalete (00-0020005) | Trends only |
| 2003 | rec | Dan Campbell (00-0002565) | Trends only |
| 2003 | rec | Brad Pyatt (00-0021969) | Trends only |
| 2003 | rec | Brian Westbrook (00-0021216) | Trends only |
| 2003 | rec | Frisman Jackson (00-0020780) | Trends only |
| 2003 | rec | Steve McNair (00-0011024) | Trends only |
| 2003 | rec | Domanick Williams (00-0021979) | Trends only |
| 2003 | rec | Kendall Newson (00-0021102) | Trends only |
| 2003 | rec | Warrick Dunn (00-0004640) | Trends only |
| 2003 | rec | Dustin Lyman (00-0019464) | Trends only |
| 2003 | rec | Eric Moulds (00-0011770) | Trends only |
| 2003 | rec | Lee Suggs (00-0022180) | Trends only |
| 2003 | rec | Jonathan Ogden (00-0012322) | Trends only |
| 2003 | rec | Marcel Shipp (00-0020022) | Trends only |
| 2003 | rec | Shawn Jefferson (00-0008313) | Trends only |
| 2003 | rec | Robert Ferguson (00-0020428) | Trends only |
| 2003 | rec | Peter Warrick (00-0019455) | Trends only |
| 2003 | rec | Moe Williams (00-0017892) | Trends only |
| 2003 | rec | Amos Zereoue (00-0018501) | Trends only |
| 2003 | rec | Travis Henry (00-0020471) | Trends only |
| 2003 | rec | Chris Fuamatu-Ma'afala (00-0005620) | Trends only |
| 2003 | rec | Jerry Rice (00-0013639) | Trends only |
| 2003 | rec | Bryan Gilmore (00-0019302) | Trends only |
| 2003 | rec | Mike Alstott (00-0000251) | Trends only |
| 2003 | rec | Dominic Rhodes (00-0019863) | Trends only |
| 2003 | rec | Jermaine Lewis (00-0009869) | Trends only |
| 2003 | rec | Donovan McNabb (00-0011022) | Trends only |
| 2003 | rec | Dennis Northcutt (00-0019650) | Trends only |
| 2003 | rec | Clinton Portis (00-0021179) | Trends only |
