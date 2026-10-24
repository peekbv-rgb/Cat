# Cat — de Catyra-avatar

De Runway-avatar **Cat** ("Cat Catyra", `761a6d44-1be3-42d5-9bda-f5ef72a72e43`)
en het kleine web-app'je dat hem belt.

**Let op: er is nog een avatar, voor een ander bedrijf.** De code van die twee
apps lijkt op elkaar omdat de ene uit de andere is gekopieerd — dat is gedeeld
loodgieterswerk, geen gedeeld project. Houd de kennisdocumenten en de persona's
strikt gescheiden, en stel vast om welke avatar het gaat voordat je een
`avatars.update` doet: die call vervangt de hele gekoppelde documentenset.

## Lees eerst de README

`README.md` is uitvoerig en actueel: installatie, elke omgevingsvariabele, de
sessielevenscyclus (`create` → poll tot `READY` → `consume` → LiveKit →
`delete`), waarom de microfoon binnen de klik-handler wordt opgevraagd, waarom
de avatar zichzelf onderbreekt bij akoestische echo, en het uitrollen naar
Render. Dat wordt hier niet herhaald. Wat hieronder staat is wat de README
*niet* zegt.

## `Knowledge/` doet niets

Er liggen vier tekstbestanden met achtergrond over Catyra en Catabatics, en
**geen enkele regel code leest ze**. `server.py` haalt de avatar alleen op om
te controleren dat hij bestaat en dat de sleutel werkt; documenten koppelen
gebeurt niet.

Er is hier dus geen builder en geen synchronisatiescript: wat Cat weet is met
de hand in Runway aan de avatar gehangen. **Een bestand in `Knowledge/`
wijzigen verandert niets** totdat iemand het opnieuw uploadt. Wie denkt een
kennisbestand bij te werken door die map te bewerken, werkt voor niets.

**Deze repo is openbaar**, en die bedrijfsteksten horen er niet in. `Knowledge/`
staat daarom in `.gitignore`. Haal die regel er niet uit.

## De promptgrens

Boven de **100.000 tekens prompt** — kennisdocumenten plus de persoonlijkheid,
bij elkaar opgeteld — valt een Runway-avatar stil. En niet met een foutmelding:
de sessie haalt gewoon `READY`, de worker komt op, er is beeld, er wordt een
audiospoor gepubliceerd en daar zit pure stilte in. Niets meldt iets — niet de
API, niet het serverlog, niet de console van de browser.

Gemeten, september 2026: 99.950 tekens spreekt, 100.182 niet. Een alinea die je
aan de persoonlijkheid toevoegt kost dus precies evenveel als een alinea
kennis. **Het enige bewijs is luisteren**; `READY` bewijst niets.

## Sleutels en toegang

`.env` bevat een **live API-sleutel**. Het bestand is gitignored en wordt uit
het zip-archief geweerd. Op Render staan `RUNWAYML_API_SECRET`, `AUTH_USER` en
`AUTH_PASSWORD` als `sync: false`, dus die komen nooit uit de repo.

Zet de basic auth aan zodra dit van buiten bereikbaar is. Een tunnel-URL of een
Render-URL is openbaar, en zonder slot kan iedereen die hem heeft het tegoed
opmaken. Sessies rekenen af zolang de worker draait.

## Vraag het voordat je uitrolt

Niet naar productie pushen zonder te vragen. Een deploy breekt een lopende
sessie af, en een sessie die halverwege afbreekt is betaald werk dat niets
heeft opgeleverd.
