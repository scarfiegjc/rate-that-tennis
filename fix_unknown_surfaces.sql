-- ratethat.tennis — Fix all Unknown tournament surfaces
-- Run once against Railway DB to clean up any remaining Unknown surfaces.
-- The pipeline.py fix (defaulting to Hard when no keyword match) prevents new ones,
-- but this handles any records already stuck as Unknown.

-- Step 1: Clay tournaments
UPDATE tournaments
SET surface_id = (SELECT id FROM surfaces WHERE name = 'Clay')
WHERE surface_id IS NULL
   OR surface_id = (SELECT id FROM surfaces WHERE name = 'Unknown')
   AND (
       name ILIKE '%roland garros%' OR name ILIKE '%french open%'
    OR name ILIKE '%rome%' OR name ILIKE '%italian open%' OR name ILIKE '%internazionali%'
    OR name ILIKE '%monte carlo%' OR name ILIKE '%monte-carlo%'
    OR name ILIKE '%madrid%'
    OR name ILIKE '%barcelona%' OR name ILIKE '%munich%' OR name ILIKE '%hamburg%'
    OR name ILIKE '%estoril%' OR name ILIKE '%oeiras%' OR name ILIKE '%porto%' OR name ILIKE '%portugal open%'
    OR name ILIKE '%geneva%' OR name ILIKE '%lyon%'
    OR name ILIKE '%kitzbuh%' OR name ILIKE '%umag%' OR name ILIKE '%gstaad%'
    OR name ILIKE '%bastad%' OR name ILIKE '%båstad%'
    OR name ILIKE '%buenos aires%' OR name ILIKE '%rio open%' OR name ILIKE '%santiago%'
    OR name ILIKE '%cordoba%' OR name ILIKE '%córdoba%'
    OR name ILIKE '%marrakech%' OR name ILIKE '%marrakesh%' OR name ILIKE '%casablanca%'
    OR name ILIKE '%houston%' OR name ILIKE '%charleston%'
    OR name ILIKE '%bucharest%' OR name ILIKE '%iasi%' OR name ILIKE '%iași%'
    OR name ILIKE '%warsaw%' OR name ILIKE '%palermo%' OR name ILIKE '%lausanne%'
    OR name ILIKE '%prague%' OR name ILIKE '%bogota%' OR name ILIKE '%bogotá%'
    OR name ILIKE '%istanbul%' OR name ILIKE '%athens%'
    OR name ILIKE '%genova%' OR name ILIKE '%genoa%' OR name ILIKE '%cagliari%'
    OR name ILIKE '%parma%' OR name ILIKE '%napoli%' OR name ILIKE '%naples%'
    OR name ILIKE '%forli%' OR name ILIKE '%forlì%'
    OR name ILIKE '%perugia%' OR name ILIKE '%barletta%' OR name ILIKE '%francavilla%'
    OR name ILIKE '%reggio emilia%' OR name ILIKE '%bordeaux%'
    OR name ILIKE '%split%' OR name ILIKE '%zagreb%'
    OR name ILIKE '%rabat%' OR name ILIKE '%tunis%' OR name ILIKE '%morocco%'
    OR name ILIKE '%valencia%' AND name NOT ILIKE '%indoor%'
    OR name ILIKE '%strasbourg%'
    OR name ILIKE '%salzbur%'
   );

-- Step 2: Grass tournaments
UPDATE tournaments
SET surface_id = (SELECT id FROM surfaces WHERE name = 'Grass')
WHERE surface_id IS NULL
   OR surface_id = (SELECT id FROM surfaces WHERE name = 'Unknown')
   AND (
       name ILIKE '%wimbledon%'
    OR name ILIKE '%queen%s%' OR name ILIKE '%cinch championships%'
    OR name ILIKE '%halle%' OR name ILIKE '%terra wortmann%'
    OR name ILIKE '%eastbourne%' OR name ILIKE '%rothesay%'
    OR name ILIKE '%mallorca%'
    OR name ILIKE '%newport%' OR name ILIKE '%hall of fame%'
    OR name ILIKE '%den bosch%' OR name ILIKE '%rosmalen%' OR name ILIKE '%libema%'
    OR name ILIKE '%birmingham%' OR name ILIKE '%bad homburg%'
    OR name ILIKE '%nottingham%' OR name ILIKE '%ilkley%' OR name ILIKE '%surbiton%'
    OR name ILIKE '%boss open%' OR name ILIKE '%bett1%'
   );

-- Step 3: Indoor Hard tournaments
UPDATE tournaments
SET surface_id = (SELECT id FROM surfaces WHERE name = 'Indoor Hard')
WHERE surface_id IS NULL
   OR surface_id = (SELECT id FROM surfaces WHERE name = 'Unknown')
   AND (
       name ILIKE '%atp finals%' OR name ILIKE '%nitto atp%' OR name ILIKE '%wta finals%'
    OR name ILIKE '%next gen finals%'
    OR name ILIKE '%paris masters%' OR name ILIKE '%bercy%' OR name ILIKE '%bnp paribas masters%'
    OR name ILIKE '%vienna%' OR name ILIKE '%erste bank%'
    OR name ILIKE '%basel%' OR name ILIKE '%swiss indoors%'
    OR name ILIKE '%metz%' OR name ILIKE '%moselle%'
    OR name ILIKE '%stockholm%' OR name ILIKE '%rotterdam%' OR name ILIKE '%abn amro%'
    OR name ILIKE '%marseille%' OR name ILIKE '%open 13%'
    OR name ILIKE '%sofia%' OR name ILIKE '%antwerp%'
    OR name ILIKE '%moscow%' OR name ILIKE '%kremlin%'
    OR name ILIKE '%tel aviv%' OR name ILIKE '%astana%'
    OR name ILIKE '%ostrava%' OR name ILIKE '%agel%'
    OR name ILIKE '%linz%' OR name ILIKE '%upper austria%'
    OR name ILIKE '%saint petersburg%' OR name ILIKE '%st. petersburg%'
    OR name ILIKE '%florence%' AND name ILIKE '%indoor%'
    OR name ILIKE '%diriyah%'
   );

-- Step 4: Everything else that's still Unknown → Hard (the modal surface)
UPDATE tournaments
SET surface_id = (SELECT id FROM surfaces WHERE name = 'Hard')
WHERE surface_id = (SELECT id FROM surfaces WHERE name = 'Unknown')
   OR surface_id IS NULL;

-- Verify
SELECT s.name AS surface, COUNT(*) AS tournament_count
FROM tournaments t
LEFT JOIN surfaces s ON s.id = t.surface_id
GROUP BY s.name
ORDER BY tournament_count DESC;
