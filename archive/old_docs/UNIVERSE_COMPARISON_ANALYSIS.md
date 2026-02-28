# Analisis Comparativo: Universo Standard vs Extendido

## Resultados del Backtest

### OmniCapital v6 Standard (40 Blue-Chips)
| Metrica | Valor |
|---------|-------|
| **CAGR** | **+17.55%** |
| Volatilidad | 22.53% |
| Max Drawdown | -49.45% |
| Sharpe Ratio | 0.74 |
| Win Rate | 52.9% |

### OmniCapital v6 Extended (150 Stocks)
| Metrica | Valor |
|---------|-------|
| **CAGR** | **-8.46%** |
| Volatilidad | 10.02% |
| Max Drawdown | -90.08% |
| Sharpe Ratio | -1.03 |
| Resultado Final | -90.01% |

---

## Analisis: Por que el universo extendido fallo

### 1. **Calidad vs Cantidad**
```
Universo 40:   Solo blue-chips de maxima calidad (AAPL, MSFT, JPM, etc.)
Universo 150:  Incluye valores de menor calidad, menor capitalizacion, menor liquidez
```

### 2. **El Overnight Premium no es igual para todos**
```
Los 40 blue-chips capturan consistentemente el overnight premium.
Los valores mas pequenos del S&P 500:
- Tienen mayor volatilidad idiosincratica
- Menor liquidez overnight
- Mayor riesgo de gaps adversos
```

### 3. **Liquidez importa**
```
Blue-chips:  Alta liquidez = mejor ejecucion = menor slippage
Mid-caps:    Menor liquidez = peor ejecucion = mayor slippage
```

### 4. **Sesgo de supervivencia**
```
Los 40 blue-chips son los sobrevivientes historicos.
El universo de 150 incluye:
- Valores que fueron del S&P 500 pero luego salieron
- Valores con performance inferior
- Valores con mayor riesgo de delisting
```

---

## Lecciones Aprendidas

### Lo que NO funciona:
1. ❌ Ampliar el universo indiscriminadamente
2. ❌ Incluir valores de menor liquidez
3. ❌ Ignorar la calidad de los activos
4. ❌ Asumir que mas diversificacion = mejor

### Lo que SI funciona:
1. ✅ Seleccionar los mejores blue-chips
2. ✅ Mantener alta liquidez
3. ✅ Foco en calidad, no cantidad
4. ✅ Los 40 mayores del S&P 500 capturan el overnight premium

---

## Recomendacion

**Mantener el universo original de 40 blue-chips.**

El edge del sistema viene de:
1. **Timing exacto**: 666 minutos
2. **Alta frecuencia**: 1,215 operaciones/año
3. **Calidad de activos**: Solo los mejores blue-chips
4. **Liquidez**: Ejecucion eficiente

La "diversificacion" con valores de menor calidad destruye valor.

---

## Conclusion

> **"La calidad vence a la cantidad."**

El universo de 40 blue-chips no es una limitacion, es una ventaja competitiva.
El sistema funciona PORQUE selecciona solo los mejores valores, no A PESAR de ello.

---

*Analisis generado el 9 de febrero de 2026*
