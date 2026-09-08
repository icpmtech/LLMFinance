def explain_technical_indicators(data: dict) -> dict:
    """Gera explicações simples a partir dos arrays devolvidos por get_technical_indicators."""
    import numpy as np

    def last(arr):
        if not arr:
            return None
        for v in reversed(arr):
            if v is not None and not (isinstance(v, float) and np.isnan(v)):
                return float(v)
        return None

    def first_valid(arr):
        for v in arr:
            if v is not None and not (isinstance(v, float) and np.isnan(v)):
                return float(v)
        return None

    def trend(arr):
        if not arr:
            return "indisponível"
        start = first_valid(arr)
        end = last(arr)
        if start is None or end is None or start == 0:
            return "indisponível"
        ch = (end - start) / abs(start)
        if ch > 0.05:
            return "subida"
        if ch < -0.05:
            return "descida"
        return "lateral"

    def slope_direction(arr):
        if len(arr) < 5:
            return "indisponível"
        clean = [float(v) for v in arr if v is not None and not (isinstance(v, float) and np.isnan(v))]
        if len(clean) < 5:
            return "indisponível"
        recent = clean[-5:]
        if recent[-1] > recent[0] * 1.01:
            return "subir"
        if recent[-1] < recent[0] * 0.99:
            return "descer"
        return "estabilizar"

    price = data.get("price", [])
    sma20 = data.get("sma20", [])
    sma50 = data.get("sma50", [])
    sma200 = data.get("sma200", [])
    rsi14 = data.get("rsi14", [])
    macd = data.get("macd", [])
    macd_signal = data.get("macd_signal", [])
    macd_hist = data.get("macd_histogram", [])
    bb_upper = data.get("bb_upper", [])
    bb_lower = data.get("bb_lower", [])
    atr14 = data.get("atr14", [])
    obv = data.get("obv", [])

    lp = last(price)
    ls20 = last(sma20)
    ls50 = last(sma50)
    ls200 = last(sma200)
    lr = last(rsi14)
    lm = last(macd)
    lms = last(macd_signal)
    lmh = last(macd_hist)
    lbu = last(bb_upper)
    lbl = last(bb_lower)
    la = last(atr14)

    # Médias móveis / tendência
    above_all = False
    below_all = False
    if lp is not None and ls20 is not None and ls50 is not None and ls200 is not None:
        above_all = lp > ls20 > ls50 > ls200
        below_all = lp < ls20 < ls50 < ls200
        if above_all:
            sma_text = "preço acima de todas as médias — tendência de alta forte"
        elif below_all:
            sma_text = "preço abaixo de todas as médias — tendência de baixa forte"
        elif lp > ls50:
            sma_text = "preço acima da SMA 50 — tendência de curto/médio prazo positiva"
        elif lp < ls50:
            sma_text = "preço abaixo da SMA 50 — tendência de curto/médio prazo negativa"
        else:
            sma_text = "preço próximo das médias — tendência indefinida"
    else:
        sma_text = "médias móveis indisponíveis para este período"

    # RSI
    if lr is not None:
        if lr > 70:
            rsi_text = f"RSI {lr:.1f} indica sobrecompra (possível correção)"
        elif lr < 30:
            rsi_text = f"RSI {lr:.1f} indica sobrevenda (possível recuperação)"
        else:
            rsi_text = f"RSI {lr:.1f} está na zona neutra (30–70)"
    else:
        rsi_text = "RSI indisponível"

    # MACD
    if lm is not None and lms is not None and lmh is not None:
        cross = ""
        if len(macd) >= 2 and len(macd_signal) >= 2:
            prev_m = macd[-2]
            prev_s = macd_signal[-2]
            cur_m = macd[-1]
            cur_s = macd_signal[-1]
            if prev_m <= prev_s and cur_m > cur_s:
                cross = "cruzamento para cima recente (sinal de compra)"
            elif prev_m >= prev_s and cur_m < cur_s:
                cross = "cruzamento para baixo recente (sinal de venda)"
        if not cross:
            cross = "acima da linha de sinal" if lm > lms else "abaixo da linha de sinal"
        hist_dir = "a expandir" if lmh > 0 else "a contraír"
        macd_text = f"MACD {cross}; histograma {lmh:.4f} e {hist_dir}"
    else:
        macd_text = "MACD indisponível"

    # Bollinger
    if lp is not None and lbu is not None and lbl is not None and lbu != lbl:
        pos = (lp - lbl) / (lbu - lbl)
        if pos > 0.95:
            bb_text = "preço na banda superior — possível sobrecompra/extensão"
        elif pos < 0.05:
            bb_text = "preço na banda inferior — possível sobrevenda"
        elif pos > 0.6:
            bb_text = "preço na metade alta das bandas — momentum positivo"
        elif pos < 0.4:
            bb_text = "preço na metade baixa das bandas — momentum negativo"
        else:
            bb_text = "preço no centro das bandas — consolidação"
    else:
        bb_text = "Bandas de Bollinger indisponíveis"

    # ATR
    if la is not None and lp is not None and lp != 0:
        pct = la / lp * 100
        if pct > 3:
            atr_text = f"ATR {la:.3f} ({pct:.1f}% do preço) — volatilidade muito elevada"
        elif pct > 1.5:
            atr_text = f"ATR {la:.3f} ({pct:.1f}% do preço) — volatilidade elevada"
        else:
            atr_text = f"ATR {la:.3f} ({pct:.1f}% do preço) — volatilidade moderada/baixa"
    else:
        atr_text = "ATR indisponível"

    # OBV
    obv_dir = slope_direction(obv)
    if obv_dir == "subir":
        obv_text = "OBV está a subir — confirma pressão compradora no volume"
    elif obv_dir == "descer":
        obv_text = "OBV está a descer — indica pressão vendedora no volume"
    else:
        obv_text = "OBV está estável — volume não confirma direção clara"

    # Sinal combinado simples
    signals = []
    if above_all:
        signals.append("tendência forte de alta")
    if below_all:
        signals.append("tendência forte de baixa")
    if lr is not None and lr > 70:
        signals.append("sobrecompra")
    if lr is not None and lr < 30:
        signals.append("sobrevenda")
    if lm is not None and lms is not None and lm > lms:
        signals.append("momento de compra (MACD)")
    if lm is not None and lms is not None and lm < lms:
        signals.append("momento de venda (MACD)")
    if obv_dir == "subir":
        signals.append("volume a confirmar alta")
    if obv_dir == "descer":
        signals.append("volume a confirmar baixa")

    if not signals:
        combined = "sem sinais extremos; aguardar confirmação"
    else:
        combined = "; ".join(signals)

    price_trend = trend(price)
    summary = (
        f"No período analisado o preço apresenta tendência de {price_trend}. "
        f"{sma_text}. {rsi_text}. {macd_text}. "
        f"{bb_text}. {atr_text}. {obv_text}. "
        f"Sinal combinado: {combined}."
    )

    return {
        "summary": summary,
        "price_trend": price_trend,
        "sma_analysis": sma_text,
        "rsi_analysis": rsi_text,
        "macd_analysis": macd_text,
        "bb_analysis": bb_text,
        "atr_analysis": atr_text,
        "obv_analysis": obv_text,
        "combined_signal": combined,
    }
