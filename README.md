# PDF-anonymisoija

Työkalu PDF-dokumenttien henkilötietojen anonymisointiin ennen tekoälylle lähettämistä.

## Toimintaperiaate

1. **Lataa PDF** → työkalu tunnistaa henkilötiedot kolmessa kerroksessa
2. **Tarkista löydökset** → hyväksy, hylkää tai lisää tietoja manuaalisesti
3. **Anonymisoi** → saat tekstin jossa nimet ym. on korvattu placeholdereilla (esim. `⟦HLÖ_0001⟧`)
4. **Anna tekoälylle** → kopioi teksti ChatGPT:lle, Geminille tai Claudelle
5. **De-anonymisoi** → liitä tekoälyn vastaus takaisin, alkuperäiset tiedot palautuvat

## Tunnistuskerrokset

| Kerros | Teknologia | Tunnistaa |
|--------|-----------|-----------|
| 1 | Microsoft Presidio + spaCy | Nimet, organisaatiot, sijainnit, puhelinnumerot, sähköpostit |
| 2 | Regex | HETU, Y-tunnus, IBAN, luottokortit, IP-osoitteet, sähköpostit |
| 3 | Qwen3:27b (Ollama) | Kontekstuaaliset ja epäselvät tapaukset |

## Vaatimukset

- Python 3.12+
- Node.js 18+
- [Ollama](https://ollama.com) asennettuna ja käynnissä
- Qwen3:27b-malli Ollamassa (`ollama pull qwen3:27b`)

## Asennus

### 1. Kloonaa repositorio

```bash
git clone <repo-url>
cd anonymisoija
```

### 2. Luo virtuaaliympäristö ja asenna riippuvuudet

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

pip install -r requirements.txt
```

### 3. Asenna spaCy-kielimallit

```bash
python -m spacy download en_core_web_lg
python -m spacy download fi_core_news_lg
```

### 4. Asenna frontend-riippuvuudet

```bash
cd frontend
npm install
cd ..
```

### 5. Konfiguraatio

Kopioi `.env.example` → `.env` ja muokkaa tarvittaessa:

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:27b
MAX_PDF_SIZE_MB=20
SESSION_TTL_MINUTES=60
```

## Käynnistys

### Backend (PowerShell 1)

```powershell
cd C:\Projektit\anonymisoija
.\venv\Scripts\activate
uvicorn main:app --reload
```

Backend käynnistyy osoitteessa `http://localhost:8000`

API-dokumentaatio: `http://localhost:8000/docs`

### Frontend (PowerShell 2)

```powershell
cd C:\Projektit\anonymisoija\frontend
npm run dev
```

Frontend käynnistyy osoitteessa `http://localhost:5173`

### Ollama (PowerShell 3, jos ei käynnissä)

```powershell
ollama serve
```

## Hakemistorakenne

```
anonymisoija/
├── main.py                  # FastAPI-sovellus, endpointit
├── requirements.txt         # Python-riippuvuudet
├── backend/
│   ├── config.py            # Asetukset (.env)
│   ├── anonymizer/
│   │   └── placeholder.py   # Placeholder-engine, anonymisointi/de-anonymisointi
│   ├── pdf/
│   │   ├── parser.py        # PDF → teksti (PyMuPDF)
│   │   └── generator.py     # Teksti → PDF (ReportLab)
│   ├── pii/
│   │   ├── engine.py        # Kerrosten koordinointi
│   │   ├── presidio_layer.py # Kerros 1: Presidio
│   │   ├── regex_layer.py   # Kerros 2: Suomalaiset regex-säännöt
│   │   └── llm_layer.py     # Kerros 3: Qwen3:27b
│   └── session/
│       └── store.py         # Sessiovarasto (SQLite)
├── frontend/
│   ├── src/
│   │   └── App.jsx          # React-käyttöliittymä
│   └── package.json
└── test_backend.py          # Testit
```

## API-endpointit

| Metodi | Endpoint | Kuvaus |
|--------|----------|--------|
| POST | `/api/analyze` | Lataa PDF, tunnistaa PII:t |
| POST | `/api/anonymize` | Anonymisoi sessio |
| POST | `/api/mapping/add` | Lisää PII manuaalisesti |
| POST | `/api/mapping/remove` | Poista PII listalta |
| POST | `/api/mapping/confirm` | Vahvista/hylkää epävarma PII |
| POST | `/api/deanonymize` | De-anonymisoi LLM-vastaus |
| POST | `/api/deanonymize/pdf` | De-anonymisoi ja luo PDF |
| GET | `/api/sessions/{id}` | Hae session tila |
| GET | `/api/sessions/{id}/text` | Hae alkuperäinen teksti |
| DELETE | `/api/sessions/{id}` | Poista sessio |
| DELETE | `/api/sessions` | Poista kaikki sessiot |
| GET | `/api/health` | Terveystarkistus |

## Placeholder-formaatti

```
⟦HLÖ_0001⟧  – Henkilö
⟦ORG_0001⟧  – Organisaatio
⟦PAIK_0001⟧ – Sijainti
⟦YTUN_0001⟧ – Y-tunnus
⟦HETU_0001⟧ – Henkilötunnus
⟦IBAN_0001⟧ – IBAN
⟦PUH_0001⟧  – Puhelinnumero
⟦EMAIL_0001⟧ – Sähköposti
```

Merkit `⟦` ja `⟧` ovat harvinaisia Unicode-merkkejä jotka LLM:t jättävät tyypillisesti koskemattomiksi.

## Tunnetut rajoitukset

- Skannatut PDF:t (kuvatiedostot) eivät toimi – tarvitaan tekstikerros
- Englanninkieliset yritysnimet suomenkielisissä dokumenteissa voivat jäädä tunnistamatta → lisää manuaalisesti
- Virolainen rekisterinumero (8 numeroa) tunnistetaan matalalla luottamuksella → vaatii käyttäjän vahvistuksen
- LLM-kerros (Qwen3:27b) vaatii Ollamaan asennettua mallia ja voi olla hidas

## Testit

```powershell
pytest test_backend.py -v
```
