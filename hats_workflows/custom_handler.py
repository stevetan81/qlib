"""Alpha158 + 自定义因子 handler。

在 Alpha158 的 158 个因子基础上，追加 6 个已验证的自定义 alpha 因子，
这些因子已预计算并存储在 Qlib 二进制数据中。
"""

from qlib.contrib.data.handler import Alpha158


class Alpha158PlusCustom(Alpha158):
    """Alpha158 + 6 个 HATS 自定义因子 = 164 个特征。"""

    CUSTOM_FACTORS = [
        ("$alpha_adx_trend", "ALPHA_ADX_TREND"),
        ("$alpha_boll_position", "ALPHA_BOLL_POSITION"),
        ("$alpha_cci_extreme", "ALPHA_CCI_EXTREME"),
        ("$alpha_rsi_divergence", "ALPHA_RSI_DIVERGENCE"),
        ("$alpha_macd_hist", "ALPHA_MACD_HIST"),
        ("$alpha_winner_rate", "ALPHA_WINNER_RATE"),
    ]

    def get_feature_config(self):
        fields, names = super().get_feature_config()
        custom_fields = [f for f, _ in self.CUSTOM_FACTORS]
        custom_names = [n for _, n in self.CUSTOM_FACTORS]
        return fields + custom_fields, names + custom_names
