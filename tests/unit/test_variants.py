from euro2core.sources.numista.variants import base_title, variant_kind


def test_variant_kind_detects_coloured_and_hologram_editions():
    assert variant_kind("2 Euros (World AIDS Day; Coloured)") == "coloured"
    assert variant_kind("2 Euros (European Union Flag; Multicoloured)") == "coloured"
    assert variant_kind("2 Euros - Henri I (Feierstëppler - hologram version)") == "hologram"
    assert variant_kind("2 Euros - Henri I (Chamber of Deputies - classic version)") is None
    assert variant_kind("2 Euros (World AIDS Day)") is None


def test_base_title_strips_edition_suffixes():
    assert base_title("2 Euros (World AIDS Day; Coloured)") == "2 Euros (World AIDS Day)"
    assert (
        base_title("2 Euros - Henri I (Chamber of Deputies - classic version)")
        == "2 Euros - Henri I (Chamber of Deputies)"
    )
    assert (
        base_title("2 Euros - Henri I (Feierstëppler - hologram version)")
        == "2 Euros - Henri I (Feierstëppler)"
    )
    assert base_title("2 Euros (Tarxien Temples)") == "2 Euros (Tarxien Temples)"
