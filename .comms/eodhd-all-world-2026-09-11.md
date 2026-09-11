# EODHD All World — compra, enlace y sonda (2026-09-11)

**From:** Grok
**Para:** Claude (acceso compartido; la clave NO esta aqui)

Lucas compro **EOD Historical Data All World**. La API esta enlazada en esta maquina y la
sonda de deslistados que Yahoo tenia a ~0 % ahora trae historia. Norgate Platinum ya no
es el unico camino para los **precios** de TASK-403. La membresia PIT sigue siendo el
registro publico 2010-2026 (nota `.comms/russell-pit-free-record-2026-09-10.md`).

## Configuracion (esta maquina)

| | |
|---|---|
| Token | `hydra_screener_local/.env` -> `EODHD_API_TOKEN` (**gitignorado**; nunca al board ni a git) |
| Cuenta | Lucas Abugattas / `lucas.as@dxlapparel.com` |
| Plan medido | `subscriptionType=monthly`, `subscriptionMode=paid`, Stripe, **100_000** calls/dia |
| Endpoint | `https://eodhd.com/api/...` |
| Simbolo US | `TICKER.US` |
| Campos EOD | `date, open, high, low, close, adjusted_close, volume` (`close` = as-printed, `adjusted_close` = split/div) |
| Sonda | `experiments/_lab_scratch/probe_eodhd.py` (scratch gitignorado) |

Como leerlo (Claude, mismo arbol):

```
# hydra_screener_local/.env  (no commitear)
EODHD_API_TOKEN=...
```

`GET https://eodhd.com/api/user?api_token=$EODHD_API_TOKEN&fmt=json` confirma el plan.

## Sonda, mismos nombres que Yahoo no precio

Pedido `from=2005-01-01` `to=2026-09-01` **despues** del pago (antes, plan free: 1 ano y TWTR/AAWW/SIVB vacios):

| ticker | n | primer dia | ultimo dia | close ultimo |
|---|---|---|---|---|
| AAPL.US | 5450 | 2005-01-03 | 2026-09-01 | 325.13 |
| TWTR.US | 2259 | 2013-11-07 | **2022-10-27** | 53.70 |
| AAWW.US | 4548 | 2005-01-03 | **2023-03-24** | 102.48 |
| SIVB.US | 4577 | 2005-01-03 | **2023-03-09** | 106.04 |
| FRC.US | 3109 | 2010-12-09 | **2023-05-02** | 3.51 |
| LEH.US | 934 | 2005-01-03 | **2008-09-17** | 0.13 |
| AABA.US | 3713 | 2005-01-03 | **2019-10-02** | 19.63 |
| BBBY.US | 5450 | 2005-01-03 | 2026-09-01 | 3.69 |
| SBNY.US | 5440 | 2005-01-03 | 2026-09-01 | 0.32 |

Lista US delistados: **60.062** nombres (TWTR, AAWW, BBBY, FRC, LEH, SIVB, AABA estan).

**BBBY y SBNY siguen hasta hoy.** Es el defecto TASK-325 (ticker reutilizado / OTC). EODHD **no** usa el sufijo `-YYYYMM` de Norgate; la identidad hay que tomarla de la lista de delistados (Code / ISIN), no del simbolo vivo.

## Que desbloquea y que no

- Desbloquea la mitad **precios** de TASK-403 (close + adjusted_close, historia 2005+ en la sonda).
- **No** sustituye constituyentes PIT Russell (EODHD no los tiene; ya estan en el registro gratis).
- **No** hay `EodhdClient` todavia. `build_russell_pit.py` sigue esperando `NorgateClient` (tres funciones). El siguiente paso de codigo es un cliente EODHD con el mismo ancho, membresia del registro gratis, precios de EODHD, vallas de cobertura/sufijo/estricto intactas. Nada de eso se ha tocado.
- Norgate Platinum (630 USD/ano) **ya no es requisito** para los precios. Sigue siendo una opcion si se quiere su membresia PIT nativa y el sufijo `-YYYYMM`.

## Resto del tablero (para no perder el hilo)

- PR **#75** (`feat/task-420-421-hard-postpone`): TASK-420 y 421 listas, 8/8 checks verdes, sin review de Claude.
- TASK-422 abierta (sentencia que salta en `data/fetch.py`); no corre prisa.
- 412 / 414 despues del settle verificado.
- Operativo viernes 2026-09-11: libro vivo dentro de ~2 h del cierre; si Yahoo recargo, reintentar, nunca `--force`.
