# Megvalósítás és ellenőrzés – 2026-11-25

A `KiCadDiffView.md` első helyi változata elkészült. Az alábbi ellenőrzések
a kezdeti megvalósításra vonatkoznak; a projekt azóta a saját `KiCadDiffView`
Git-repóba került. A két korábbi referenciaalkalmazás változatlan.

Elkészült a repó-/projekt-/commitválasztás, a sorba állított generálás és mentett
eredmények kezelése; a Schematics, PCB és Components fülek; az Overlay,
Side by Side, Swipe és Colored nézetek; a közös fizikai vászon, teljes hierarchia
és réteglista; a szabványos és egyedi alkatrészmezők összehasonlítása.
A forrás Docker-csatolása és a konténer gyökérfájlrendszere read-only,
minden futásidejű adat külön írható data könyvtárba kerül.

## Lefuttatott ellenőrzések

- Python unittest: 45 tesztből 44 sikeres, 1 külön indítandó integrációs teszt kihagyva.
- Ugyanaz az integrációs teszt külön, `KICADDIFFVIEW_REAL_TESTS=1` mellett sikeres:
  mindkét tesztprojekt teljesen újragenerálva a `svg-components-3` feldolgozóval.
- Armfed: 11 schematic-lap, 36 PCB-réteg; commitok `7c96f10` → `bed6b9b`.
- lea6s_to_maxm10s: 1 schematic-lap, 24 PCB-réteg; commitok `7b75987` → `ea63d8b`.
- A valós teszt ellenőrizte az összes SVG közös vásznát, a rétegeket,
  az Armfed Edge.Cuts geometriáját, az alkatrészlistákat és a forrásfájlok,
  valamint a Git-metaadatok változatlan ellenőrzőösszegét.
- A Colored nézet raszterizált pixeltesztje az előírt három pontos RGB-színt
  és az átlátszó hátteret ellenőrizte librsvg/Cairo segítségével.
- Mind az 5 frontend regressziós tesztcsoport sikeres.
- Szigorú TypeScript 6.0.3 ellenőrzés sikeres.
- Offline frontend build, JavaScript-szintaxis és indítószkriptek szintaxisa rendben.
- Külön kódellenőrzés után javítva és újraellenőrizve a Vite asset-útvonalak,
  az átlátszó Swipe-felek, az egyedi rétegnevek, a Components mezősorok,
  és a többegységes alkatrészek eltérő mezőértékeinek megőrzése.

## Megmaradt kézi végellenőrzés

A munkamenetben a Docker socket és a hálózati letöltés nem hozzáférhető,
HTTP-port nem nyitható, és a headless Firefox sem indult el. Emiatt a Docker-image
buildjét, a Vite production buildet és az élő böngészős megjelenítést itt nem
lehetett ellenőrizni. A működő offline build elkészült; az indítás a saját,
Dockerhez hozzáférő terminálból: `./build_docker_image.sh`, majd
`./run.sh /path/to/repositories`; megnyitás: `http://localhost:8080`.

A valós összehasonlítások a korábbi tesztkörnyezet data könyvtárában maradtak;
ezek nem részei a KiCadDiffView repónak és nem kerültek át az új projektmappába.
A kézi használati lépések és az első változat támogatási határai a `README.md`
fájlban találhatók.

## Átmásolás és átnevezés – 2026-11-26

- Mind a 37 forrásfájl átvizsgálva és átmásolva a KiCadDiffView Git-repóba;
  a data, a generált buildek és a gyorsítótárak nem kerültek át.
- Frissítve a felület címe és fejlécneve, az API címe és indítási üzenete,
  a Docker-image/konténer neve, az npm-csomagnév, a környezeti változók,
  a böngésző mentési kulcsai, a tesztek és a dokumentáció hivatkozásai.
- A specifikáció neve `KiCadDiffView.md`; a futásidejű környezeti változók
  előtagja `KICADDIFFVIEW_`, a Docker-nevek kisbetűsen `kicaddiffview`.
- A célrepó eredeti Git-adatai, GitHub remote-ja és MIT licence változatlan;
  az MIT licenc az npm-metaadatokban és a Docker-image-ben is szerepel.
- Az új könyvtárból futtatva: 44 Python-teszt sikeres, a külön indítandó
  valós projektintegráció kihagyva; mind az 5 frontend tesztcsoport,
  a szigorú TypeScript-ellenőrzés és az offline frontend build sikeres.
- A forrásfájlok és a célrepó Git-adatainak ellenőrzőösszege változatlan.
  A tesztek átmeneti adatkönyvtára takarítva; a célmappában nincs data.

## Docker-scriptek szétválasztása – 2026-11-26

- Külön publikus image-builder és kötelező könyvtárparaméteres konténerindító
  készült; a helyi fejlesztői wrapper Git-ignore alá került.
- Mindhárom script shell-szintaxisa és futtatási jogosultsága rendben.
- A 13 indítási teszt Docker-helyettesítővel ellenőrzi a build/indítás különválasztását,
  az útvonalakat, kapcsolókat, hibakezelést és a read-only forráscsatolást.
  A forrás és a data átfedő könyvtárfáját az indító visszautasítja.
- A helyi wrapper sikeres és hibás buildjét a két valódi publikus scripttel,
  helyettesített Dockerrel külön ellenőriztük; a környezeti beállítások öröklődnek.
- Teljes Python-tesztkör: 60 tesztből 59 sikeres, 1 külön indítandó valós
  projektintegráció kihagyva. Valódi Docker buildet/indítást ez az ellenőrzés nem futtatott.

## Belső hálózati/VPN-es elérés – 2026-11-26

- A Docker-port minden hálózati interfészen elérhető (`PORT:8080` publikálás),
  külön címparaméter vagy szervernévlista nélkül.
- A szerver mindkét HTTP-adaptere érvényes Host fejléceket fogad el IP- és
  szervernév-korlátozás nélkül. A módosító kérések azonos eredetét ellenőrzi.
- A natív HTTP-handler memóriabeli kéréseivel ellenőriztük a különböző
  szervernevek elérését és az idegen Origin elutasítását.
- A hálózati működés megbízható belső hálózatra/VPN-re készült, bejelentkezés nélkül.

## Publikus HTTPS Git-tárolók – 2026-11-26

- Elkészült a Local folders / Public Git URL választó, a háttérben sorba állított
  teljes klónozás, a tartós `data/repos` gyorsítótár és a kézi Refresh.
- A kezelt tárolók URL-je megmarad a diff metaadataiban; a kapcsolódás külön repo-ID,
  így azonos originű helyi checkout nem érintett a távoli klón törlésében.
- A Delete repository megerősítése jelzi a kapcsolódó diffek számát és becsült méretét;
  a backend is tiltja a törlést várakozó/futó kapcsolódó művelet alatt.
- Valódi helyi Git-fixture-ökkel ellenőriztük a teljes ág-/tag-előzményt,
  az alapértelmezett ág váltását, a frissítés visszaállítását, a megszakadt műveletek
  folytatását, az explicit tulajdonviszonyt és a klón+diffek együttes törlését.
  Csak a hálózati folyamathívást helyettesítettük a fixture eléréséhez;
  az éles HTTPS-korlátozás megmarad.
- Külön tesztek fedik a 900 másodperces időkorlátot, folyamatcsoport-megszakítást,
  az anonim Git-környezetet, symlink-határokat és az újraindítás utáni nyilvántartást.
- Frontend DOM/VM regressziók: URL-címkék, egyszeri automatikus megnyitás,
  frissítés utáni újratöltés, későn érkező válaszok és szelektív törlés utáni takarítás.
- A szigorú TypeScript-ellenőrzés és az offline frontend build sikeres.
  Valós Docker build/indítás, internetes HTTPS-klónozás és élő böngészős próba
  nem része ennek a korlátozott környezetben végzett ellenőrzésnek.
- Végső teljes Python-tesztkör: 91 tesztből 90 sikeres, 1 külön indítandó
  valós KiCad-integráció kihagyva. A teljes Node frontendtesztkör, a TypeScript
  6.0.3 strict ellenőrzés, az offline build, a shell-szintaxis és a diff-check sikeres.
