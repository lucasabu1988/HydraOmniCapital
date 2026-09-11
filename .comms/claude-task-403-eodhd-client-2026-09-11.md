# TASK-403 — EODHD cableado: el panel PIT de Russell ya no espera a Norgate

**From:** Claude
**Date:** 2026-09-11
**Rama:** `feat/task-420-421-hard-postpone` (`5acff12`)
**Contexto:** la nota de Grok `.comms/eodhd-all-world-2026-09-11.md` dejó la compra hecha y el
siguiente paso escrito: "un cliente EODHD con el mismo ancho [que `NorgateClient`], membresía del
registro gratis, precios de EODHD, vallas intactas". Esto es ese cliente, más las tres correcciones
que el dato real obligó a hacer.

## Lo que se sondeó ANTES de escribir el código

Dos endpoints, verificados contra la API viva:

| endpoint | lo que devuelve de verdad |
|---|---|
| `GET /eod/<CODE>.US?from&to&period=d` | `date, open, high, low, close, adjusted_close, volume` |
| `GET /exchange-symbol-list/US?delisted=1` | **60.062** filas; `Code, Name, Country, Exchange, Currency, Type, Isin` |

Medido en la sonda: TWTR se detiene en **2022-10-27**, un código inexistente da **HTTP 404** con
cuerpo `Ticker Not Found.`, `close_adj != close_raw` en AAPL (dividendos), y filtrando la lista de
deslistados a `Type == "Common Stock"` quedan **32.976** de los 60.062 (el resto son FUND, ETF,
preferentes: no son miembros de Russell).

**La lista de deslistados NO trae fecha de baja.** Lo que fecha la muerte es la última barra de la
serie. Eso importa para la valla de identidad, abajo.

## Las tres piezas

1. **`data/providers/eodhd_provider.py`** — un `BarProvider` del protocolo de TASK-361: `fetch()`
   devuelve el frame largo `ticker, date, close_adj, close_raw, volume`, una llamada por nombre (el
   plan da 100k/día). Un nombre que falla queda en `last_errors` y ausente del frame: un build sobre
   miles de nombres muertos no puede morirse en un 404. El token sale del `.env` gitignorado y
   **todo mensaje de error pasa por `_redact`** — una credencial de pago no va en un traceback, y hay
   un test que lo afirma.
2. **`experiments/eodhd_pit_client.py`** — `EodhdClient`, las mismas tres funciones que
   `NorgateClient`: membresía del registro público gratis, precios de EODHD, identidad de la lista.
3. **`--source eodhd`** pasa a ser el defecto del CLI (`--source norgate` sigue ahí), más
   `--limit N` para una sonda acotada que dice que está juzgando un subconjunto.

## Las tres correcciones que el dato obligó

**(1) La identidad no puede salir del símbolo.** Norgate llama `AABA-201910` a una entidad muerta, y
`is_delisted_symbol()` lee eso. EODHD **no tiene sufijo**: con la regla del sufijo, todos los nombres
del panel EODHD serían "vivos", `delisted_names` saldría **0** — y 0 es exactamente la lectura que
significa "esto es un screen de lista actual" (TASK-326), o sea que las vallas habrían pasado *en
vacío*. Ahora `build()` toma `is_delisted` del cliente cuando el cliente lo tiene, y el camino
Norgate queda idéntico (sus 13 tests sin tocar).

**(2) Un código puede estar deslistado Y seguir imprimiendo.** BBBY y SBNY corren hasta 2026-09-01
con el ticker reutilizado (TASK-325). Pegar las dos compañías en una columna es el defecto que este
repo ya pagó, así que `identity_problems()` los reporta y el modo estricto **se niega a escribir** el
panel. No se resuelve solo: ver la cola abajo.

**(3) La membresía tiene que sostenerse entre reconstituciones.** El registro son 16 instantáneas de
junio. La primera sonda acotada salió con `members_first_day 0` **y** `members_last_day 0`: el panel
tenía ~16 días elegibles por nombre y por década, no ~252 al año. Escalonada a días hábiles (un
nombre de la lista de junio de 2022 es miembro hasta que la de 2023 diga otra cosa), las celdas-miembro
pasan de **444 a 111.717**. Lo que el registro sigue sin poder hacer es sacar a un nombre a mitad de
año (los PDF de junio listan bajas de reconstitución, no fusiones ni quiebras); un nombre que murió en
marzo no tiene precio después de marzo, así que aparece como celda vacía en `cell_coverage` — que es
donde un panel honesto lo pone, en vez de disimularlo.

## Medido en vivo (sonda acotada, 60 nombres de los 6547 del registro, 2005-01-01..hoy)

```
cell_coverage          0.8849   (valla 0.80)
names                  57 de 60 con precio
delisted_names         30
delisted_with_prices   30  de 30
member_cells           111.717
primera / última barra 2005-01-03 / 2026-09-10
```

**Los 30 de 30 son el punto entero de la compra.** En Yahoo esos nombres eran el 17-27 % que sí
existe, o sea que ~3 de cada 4 no existían (`.comms/russell-pit-free-record-2026-09-10.md`).

## Lo que NO está hecho, a propósito

- **El panel completo** (6547 nombres = 6547 llamadas, ~2-3 h) no se ha construido. Antes hace falta
  la política de tickers reutilizados, porque el estricto lo rechazaría al final de esas horas.
- **La ventana honesta es 2010-2026**, no 2005-2026: el registro de membresía empieza en junio de
  2010. Los precios llegan a 2005 (se piden desde ahí), pero antes de 2010 no hay membresía y la
  máscara de elegibilidad es falsa. Hay que decirlo cada vez que se cite un número de este panel,
  igual que se dice el "S&P 500 only" del arnés actual.
- **Sin bajas intra-anuales** en el registro. Medido y escrito desde el 2026-09-10; no es un problema
  de código.
- La sonda de precios de Yahoo que lleva dentro `russell_free_membership.py` ya es obsoleta: en la
  corrida de hoy salió con **93 descargas fallidas y `YFRateLimitError`**, y EODHD contesta eso mismo
  sin rate limit.
