# KiCadDiffView

Helyi, böngészőből vezérelhető KiCad/Git összehasonlító alkalmazás.
A webes felület, a státuszok és az alkalmazás hibaüzeneteinek nyelve angol.

## Témák

A fejlécben Light / Dark / System választó szerepel. Alapértelmezés: System,
amely élőben követi az operációs rendszer témáját. A választást a böngésző
helyi tárolója őrzi (`kicaddiffview.theme`); tiltott tárolás mellett is működik
az aktuális munkamenetben. A téma már a felület első kirajzolása előtt érvényesül.
A világos és sötét paletta az összes kezelőelemet, táblázatot és dialógust lefedi;
a KiCad-rajzfelület Light témában fehér, Dark témában sötét.
A rajzokhoz az előírt diff-színek tartoznak.

Megvalósítás: önálló, korán betöltött `frontend/public/theme.js` vezérli a
gyökérelem témáját és a választót; CSS-változók adják a két palettát.
Az offline builder a public fájlokat is átmásolja a buildbe. Ellenőrzés:
mentett választás, élő rendszerkövetés, hibás/tiltott tárolás, teljes frontend
tesztkör, TypeScript és build; az SVG-k színezéséhez nem szükséges új export.

## Munkahatárok

Minden fejlesztés ebben a projektkönyvtárban történik. A szomszédos `kiri` és
`sksat-kicadiff` csak olvasható referencia. Módosításuk előtt mindig külön
egyeztetni kell, még későbbi módosítási kérés esetén is.

## Futtatás, adatok

- Webalkalmazás, alapból localhost:8080; beállítható belső hálózati/VPN-es elérés.
  Dockerrel vagy közvetlenül futtatható.
- Docker alatt a repógyökér kötelezően read-only bind mount.
- Külön írható `data` mount: adatbázis, munkapéldányok, exportok, képek,
  ideiglenes fájlok, gyorsítótárak, összehasonlítási előzmények.
- A forrásrepó nem változhat; mindkét commit teljes, önálló pillanatképén dolgozunk.
- A mentett eredmények újranyithatók és törölhetők; a törlés csak saját adatokat érint.
- Python háttérszolgáltatás FastAPI adapterrel; TypeScript böngészős felület.
  KiCad 9 és Git szükséges az exporthoz; Dockerben ezek beépített függőségek.

### Docker-indítás

- `build_docker_image.sh`: kizárólag a `kicaddiffview:local` image-et építi
  a script saját projektkönyvtárából. Nem hoz létre adatkönyvtárat.
- `run.sh KÖNYVTÁR`: meglévő image-ből indít konténert. A kötelező könyvtár
  egy repo vagy több repo közös gyökere lehet. Relatív útvonal az aktuális
  munkakönyvtárhoz viszonyul; automatikus build nincs.
- A `PORT` alapértéke 8080; a `DATA_DIR` alapból a script melletti `data`.
  Megadott relatív `DATA_DIR` az indítás könyvtárához viszonyul.
  A forrás és a data könyvtárfája nem fedheti át egymást.
- Mindkét publikus script támogatja a `--help` kapcsolót. A futtató scriptnek
  nincs további kapcsolója; leállítás Ctrl+C-vel.
- A helyi `build_docker_and_run.sh` fejlesztői wrapper a két publikus scriptet
  hívja. Git-ignore szabály zárja ki a publikálásból.
- A Docker-port alapból minden hálózati interfészen elérhető. Nincs szükség
  külön figyelési címre vagy szervernévlistára. Helyben localhost, távolról
  a szerver IP-je/neve és az alapértelmezett 8080-as port használható.
- Belső hálózati/VPN-es módban nincs bejelentkezés; a hozzáférő felhasználók
  közösen érik el a repókat és eredményeket. Az érvényes HTTP Host fejléc
  és a módosító kérések azonos eredetének ellenőrzése megmarad.

## Munkamenet

Repóválasztás könyvtárböngészővel, útvonalbevitellel és előzményekkel. KiCad-projekt
választás, majd két commit: alapból projektkönyvtárra szűrt előzmények, keresés,
összes commit és közvetlen SHA-bevitel. A referenciák indításkor teljes SHA-ra
oldódnak. Generálás állapotjelzéssel és hibaüzenettel, automatikus mentéssel.

## Grafikus összehasonlítás

- Fő fülek: Schematics, PCB, Components.
- Overlay, Side by Side, Swipe és Colored nézet.
- Fájl-, rajzlap- és rétegválasztó, nagyítás, mozgatás, szinkronizált nézetek.
- Minden PCB-réteg, belső és egyedi nevű rétegek is; külön ki-be kapcsolhatók.
- Közös fizikai origó, vászon és lépték minden revízióhoz/réteghez.
  Valódi geometriai elmozdulásokat nem igazítunk el.
- Colored: új #40FF40, régi #880808, változatlan #807F7F. Rétegenként készül,
  a többi nézettel közös rétegkapcsolókkal. SVG-alapú, nagyítható megoldás.
- Minden revízió saját hierarchikus rajzlapjait használjuk. Új/törölt lapok és
  rétegek egyoldalas tartalomként jelennek meg.

## Components

Külön Schematic és PCB lista. Kereshető/szűrhető, alkatrészenként kibontható
táblázat: új, törölt, módosult, változatlan. Minden szabványos és egyedi mező,
hozzáadott/törölt mezők, régi/új értékek. Egyező mezők megjeleníthetők.

A schematic teljes hierarchiája, példányok és többegységes alkatrészek helyes
azonosítása. Átszámozás lehetőség szerint módosítás. A PCB esetén footprint,
pozíció, forgatás és paneloldal is összehasonlítandó; elhelyezési eltérések külön
szűrhetők. DNP és BOM-ból kizárt valós alkatrészek is látszanak, jelölve és
szűrhetően; e státuszok változása eltérés.

## Ellenőrzés és későbbi irány

Valós projektek: Armfed/Armfed és lea6s_to_maxm10s. Bevált commitpárok:
Armfed 7c96f105c84e3abd1975e235742a56e6c79eca9a → bed6b9bbb014fc2f4fc744a7263bbc3a8737f116;
lea6s_to_maxm10s 7b75987 → ea63d8b. Ellenőrizendő a színezés, illesztés, teljes
hierarchia, összes réteg, alkatrészmezők, mentések és a forrás változatlansága.

Későbbi bővítés: hitelesített, privát GitLab/GitHub/egyéb Git-források.

## Publikus távoli tárolók

- Browse repositories: Local folders és Public Git URL fülek.
- Anonim HTTPS klónozás, teljes előzmény/ágak/tagek; projektek a távoli alapértelmezett ágból.
- Kezelt klónok kizárólag `data/repos` alatt, SQLite nyilvántartással; a helyi források továbbra is read-only.
- Újrahasználható klónok automatikus fetch nélkül; kézi Refresh, hiba esetén korábbi használható checkout.
- Klónozás/frissítés a diffekkel közös egyetlen workerben; 15 perc hálózati időkorlát, megszakítás leállításkor.
- Lista URL-lel, állapottal, frissítési dátummal, mérettel; az URL szerepel a diff metaadataiban is.
- Delete repository: megerősítés URL-lel, kapcsolódó diffek számával és becsült felszabaduló hellyel.
  Törli a kezelt klónt, ideiglenes maradványait, kapcsolódó diffjeit és előzményeit.
  A kapcsolat explicit kezelt repo-ID; azonos originű helyi checkout érintetlen marad.
- Várakozó/futó kapcsolódó művelet közben nincs törlés; helyi forráshoz nincs repo-törlési API.
- SSH, HTTP, beágyazott hitelesítési adatok, automatikus submodule/LFS nem támogatott.
