# KiCadDiffView

Helyi, böngészőből vezérelhető KiCad/Git összehasonlító. Specifikáció:
[KiCadDiffView.md](KiCadDiffView.md).
A webes felület nyelve egységesen angol.
A fejléc **Theme** választójával Light, Dark vagy System téma állítható be.
Alapból a System mód követi a rendszer témáját; a böngésző megjegyzi a választást.
A KiCad-rajzfelület Light témában fehér, Dark témában sötét hátteret kap.
A rétegek és a Colored nézet diff-színei az exportált SVG-k színeit használják.

## Indítás Dockerrel

```bash
cd KiCadDiffView
./build_docker_image.sh
./run.sh /path/to/repositories
```

Megnyitás: **http://localhost:8080**. A megadott könyvtár lehet egyetlen Git-repo
vagy több repo közös gyökérmappája. A konkrét repo, projekt és két commit
kiválasztása a böngészőben történik.

Az első build internetkapcsolatot igényel. A Docker-image tartalmazza a KiCad 9-et,
a Gitet, a Python/FastAPI hátteret és az elkészített TypeScript/Vite felületet;
a hostra ezeket nem szükséges telepíteni. Docker Compose nem szükséges.
A `build_docker_image.sh` csak image-et épít, a `run.sh` csak meglévő image-et
indít. A buildet első használatkor és a program frissítése után kell futtatni.
Hiányzó image esetén az indítás hibaüzenetben jelzi a build parancsát.

```bash
PORT=9090 DATA_DIR=/path/to/data ./run.sh /path/to/repositories
./build_docker_image.sh --help
./run.sh --help
```

- A könyvtárparaméter abszolút útvonala azonos helyre, **read-only** kerül a konténerbe.
  A webes könyvtárválasztó csak ezen a gyökéren belül böngészhet.
- A külön `DATA_DIR` (alapból a `run.sh` melletti `data`) írható `/data` csatolás.
- A forrás és a data könyvtárfája nem fedheti át egymást: egyik sem lehet a
  másikon belül. Ilyenkor külön `DATA_DIR` útvonalat kell választani.
- A relatív könyvtárparaméter és `DATA_DIR` az indítás aktuális könyvtárához
  viszonyul. Szóközös útvonalakat idézőjelek közé kell tenni.
- A konténer fájlrendszere is read-only; a program a host felhasználó UID/GID-jével fut.
- Minden munkapéldány, KiCad-beállítás, ideiglenes fájl, kép, adatbázis és eredmény
  a data alatt készül. A forrásban Git worktree, checkout, fetch vagy írás nem történik.
- A data nem része a Docker buildkörnyezetének és nincs verziókezelésre szánva.

A konténer előtérben fut; **Ctrl+C**-vel állítható le. A data tartalma megmarad.
A `run.sh` egyetlen kapcsolója a `--help`; a repókönyvtárat minden indításkor
paraméterként kell megadni.

A Docker-image neve `kicaddiffview:local`, a konténer neve `kicaddiffview`.
A közvetlen backendbeállítások `KICADDIFFVIEW_` előtagot használnak.

### Belső hálózati vagy VPN-es elérés

A Docker-indítás alapból minden hálózati interfészen publikálja a portot
(`8080:8080`), külön címbeállítás nélkül:

```bash
./run.sh /path/to/repositories
```

Helyben a **http://localhost:8080**, másik gépről a **http://SZERVER_IP:8080**
vagy a szerver neve használható. A `PORT` változóval a port továbbra is átállítható.
A módosító kérések azonos eredetének ellenőrzése hálózati használatnál is érvényes.

A hálózati mód megbízható belső hálózatra/VPN-re készült, bejelentkezés nélkül.
A hozzáférő felhasználók ugyanazokat a csatolt repókat és mentett diffeket látják.
Privát távoli Git-tárolók és többfelhasználós hitelesítés későbbi fejlesztés.

### Publikus Git-tárolók

A **Browse repositories → Public Git URL** fülön adj meg egy anonim HTTPS
klónozási URL-t (például GitHub, GitLab vagy más Git-szerver), majd **Clone and open**.
A teljes Git-előzmény, a távoli ágak és tagek a `data/repos` alá kerülnek;
a projektválasztó az alapértelmezett távoli ág aktuális projektjeit mutatja.
A commitválasztóban más ágak commitjai is elérhetők. A felületen a tároló URL-je látszik.

Az ismételt megnyitás a meglévő klónt használja, hálózati frissítés nélkül.
A **Refresh** tölti le az új commitokat és frissíti az alapértelmezett ág
munkapéldányát. Sikertelen frissítés után a korábbi használható klón megmarad.
A klónozás/frissítés és a diffkészítés közös feldolgozási soron fut;
a hálózati Git-műveletek időkorlátja 15 perc. Újraindítás után a letöltött tárolók megmaradnak.

A letöltött tárolók listája jelzi az állapotot, az utolsó sikeres frissítést és
a foglalt helyet. A **Delete repository** megerősítés után törli a kezelt klónt,
annak mentett diffjeit és munkafájljait is. A megerősítés a diffek számát és a
várhatóan felszabaduló helyet mutatja. Folyamatban levő vagy várakozó művelet
alatt a tároló nem törölhető. A helyi csatolt tárolókhoz nincs ilyen törlési művelet;
a távoli Git-szerver tartalma sem változik. Törlés után az URL újra importálható.

Csak hitelesítés nélküli HTTPS támogatott, szokásos tanúsítvány-ellenőrzéssel.
SSH, HTTP, token/jelszó az URL-ben, submodule- és Git LFS-letöltés nem támogatott.
Kizárólag távoli tárolókhoz is kötelező a `run.sh` könyvtárparamétere;
ilyenkor megadható egy külön létrehozott üres könyvtár.

## Használat

1. Nyiss meg egy helyi Git-tárolót útvonalból, az előzményekből vagy a könyvtárböngészőből;
   publikus tárolóhoz használd a **Browse repositories → Public Git URL** fület.
2. Válassz KiCad-projektet. A projektlista a Gitben követett `.kicad_pro` fájlokból készül.
3. Válassz régi és új commitot a két rádiógombos oszlopban, vagy írj be SHA-t/tag-et/branch-et.
   A lista a projekt könyvtárára szűrt; válthatsz az összes commitra, kereshetsz az üzenetekben,
   és további commitokat tölthetsz be.
   Egy commit fölé vitt egérnél buborékban megjelenik a teljes, többsoros üzenet,
   a teljes SHA, a szerző és a dátum.
4. Indítsd az összehasonlítást. Az állapot és a hiba a felületen látszik.
5. A mentett eredmények később újranyithatók. Az azonos bemenet és feldolgozóverzió
   kész eredményét újra felhasználjuk; törlés után újragenerálható.

Az eredmény fejlécében is a két commit üzenetének első sora szerepel;
föléjük vitt egérnél a teljes üzenet és azonosító látható. Új eredményeknél
ezeket az adatokat a diff mellé mentjük. Korábbi eredményeknél a repóból
olvassuk be őket; ha az már nem elérhető, az azonosító marad látható.

**Schematics / PCB:** Overlay, Side by Side, Swipe, Colored; nagyítás, egérgörgő,
mozgatás, illesztés; fájl- és rajzlapválasztó, minden PCB-réteg kapcsolóval.
A szokásos külső rétegek alapból bekapcsoltak; a belső/egyedi rétegek is elérhetők.
A réteg neve melletti kijelölés felülre emeli az aktív réteget.

**Colored:** új `#40FF40`, régi `#880808`, változatlan `#807F7F`. A színezés
rétegenként készül, önálló SVG-maszkokkal, külső képhivatkozások és fix méretű
raszteres különbségkép nélkül. Az SVG-k közös vászna megőrzi az eredeti fizikai
koordinátákat: nem központosítjuk vagy mozgatjuk egymásra a terveket.

**Components:** külön schematic és PCB lista, állapot/keresés/DNP/BOM szűrők,
kibontható régi/új mezők és egyező mezők kapcsolója. Minden szabványos és egyedi
mező szerepel. A PCB-elhelyezési eltérések külön kikapcsolhatók. Az alkatrészek
stabil azonosítóval, illetve egyértelmű referencia+rajzlap párral illeszkednek.
Többegységes alkatrésznél az egységenként eltérő mezők és jelölők értékei is
megmaradnak, az érintett egység azonosítójával együtt.

## Közvetlen helyi futtatás

Linux/WSL alatt KiCad 9 (`kicad-cli`), Git, Python 3.12+, valamint frontendépítéshez Node.js 22.12+
szükséges. A Node csak a buildhez kell, a kész felület futtatásához nem.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
npm --prefix frontend install
node scripts/build-frontend.cjs
KICADDIFFVIEW_REPO_ROOTS=/path/to/repositories python3 -B -m app.server --port 8080
```

Telepített FastAPI/uvicorn mellett az ASGI adapter fut. Függőségek nélküli helyi
fejlesztéshez ugyanaz a backend a Python standard HTTP-adapterével is indítható:

```bash
node scripts/build-frontend.cjs
KICADDIFFVIEW_REPO_ROOTS=/path/to/repositories python3 -B -m app.server --native
```

Az offline frontend-builder a rendszer Babel-csomagjait használhatja; telepített
npm-függőségekkel a Vite buildet használja. A natív szerver is alapból csak
`127.0.0.1:8080` címen érhető el. A `KICADDIFFVIEW_DATA` az adatkönyvtárat,
a `KICADDIFFVIEW_REPO_ROOTS` több, kettősponttal elválasztott repógyökeret is megadhat.
A natív szerver távoli eléréséhez a figyelési cím 0.0.0.0-ra állítható:

```bash
KICADDIFFVIEW_REPO_ROOTS=/path/to/repositories python3 -B -m app.server --host 0.0.0.0 --port 8080
```

## Ellenőrzés

```bash
mkdir -p data/test-tmp
python3 -B -m unittest discover -s tests -v
node scripts/build-frontend.cjs
node tests/frontend.test.cjs
node scripts/typecheck.cjs
```

A frontendtesztek a frontend npm-függőségeit vagy a rendszer Babel-csomagjait használják. A színek pixeltesztje
librsvg/Cairo esetén automatikusan lefut. A valós hardverprojektek teljes exportja:

```bash
KICADDIFFVIEW_REAL_TESTS=1 python3 -B -m unittest discover -s tests -p test_real_projects.py -v
```

Tesztprojektek: Armfed/Armfed (`7c96f10` → `bed6b9b`) és lea6s_to_maxm10s
(`7b75987` → `ea63d8b`). A teszt minden SVG közös vásznát, a hierarchikus lapokat,
az összes réteget és a forrásfájlok/Git-metaadatok változatlanságát ellenőrzi.

## Az első verzió határai

Modern `.kicad_pro`, `.kicad_sch` és `.kicad_pcb` fájlokra készült. A gyökér
schematic a projekt nevével egyező fájl; a kiválasztott könyvtár közvetlen PCB-fájljai
külön grafikus fájlként jelennek meg. A Components PCB-lista a projekttel egyező
nevű PCB alkatrészeit mutatja. Régi `.sch`, privát távoli tárolók, nem inicializált
submodule-ok/LFS-pontok és a repón kívüli schematic-lapok nem támogatottak.
A nem commitolt módosítások nem részei a diffnek.

A teljes lapos vászon miatt lehet üres terület a terv körül; nagyítással lehet
ráközelíteni. Nagy projekteknél a vektoros Colored SVG-k mérete jelentős lehet;
a mentett eredmények a felületen törölhetők.

A fejlesztési munkamenetben a Docker socket, a hálózati letöltés és a HTTP-portnyitás
korlátozott; a Firefox headless sem indult el. Emiatt a Docker build, a Vite production
build és az élő böngészős végellenőrzés külön, a saját terminálodból szükséges.
A backend-, SVG-pixel- és valós KiCad-export tesztek ezektől függetlenül lefuttathatók.

## Licenc

MIT; a teljes szöveg a [LICENSE](LICENSE) fájlban található.
