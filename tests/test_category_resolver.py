import json
from pathlib import Path

from app.category_resolver import _rank_categories, resolve_category
from app.models import Promotion
from app.promotion_rules import apply_promotion_rules, load_promotion_rules

CATEGORIES_CONFIG = {
    "geral": {"display_name": "Geral", "external_aliases": ["geral", "general"]},
    "eletronicos": {
        "display_name": "Eletrônicos",
        "external_aliases": ["eletronicos", "eletrônicos", "notebook"],
    },
    "games": {
        "display_name": "Games",
        "external_aliases": ["games", "ps5", "controle"],
    },
}

ROOT = Path(__file__).resolve().parents[1]
LIVE_CATEGORIES = json.loads(
    (ROOT / "config" / "categories.json").read_text(encoding="utf-8")
)
LIVE_RULES = load_promotion_rules(str(ROOT / "config"))


def _promo(title: str, **kwargs) -> Promotion:
    return Promotion(
        external_id="1",
        source=kwargs.pop("source", "aliexpress"),
        title=title,
        url="https://example.com",
        **kwargs,
    )


def test_resolve_exact_category():
    promotion = _promo("Notebook", category="eletronicos")
    assert resolve_category(promotion, CATEGORIES_CONFIG) == "eletronicos"
    assert promotion.resolved_category == "eletronicos"


def test_resolve_alias_with_accent():
    promotion = _promo("Produto", category="eletrônicos")
    assert resolve_category(promotion, CATEGORIES_CONFIG) == "eletronicos"


def test_resolve_from_tags():
    promotion = _promo("Controle", tags=["ps5", "games"])
    assert resolve_category(promotion, CATEGORIES_CONFIG) == "games"


def test_fallback_to_geral():
    promotion = _promo("Produto desconhecido", category="categoria-inexistente")
    assert resolve_category(promotion, CATEGORIES_CONFIG) == "geral"
    assert promotion.resolved_category == "geral"


def test_resolve_from_title():
    categories = {
        **CATEGORIES_CONFIG,
        "roupas": {
            "display_name": "Roupas",
            "external_aliases": ["vestido", "camiseta", "short"],
        },
        "esportes": {
            "display_name": "Esportes",
            "external_aliases": ["academia", "treino", "short academia"],
        },
    }
    promotion = _promo("Vestido Curto Feminino Plus Size Elegante", source="shopee")
    assert resolve_category(promotion, categories) == "roupas"


def test_academia_conjunto_prefers_esportes_over_short():
    categories = {
        "roupas": {
            "display_name": "Roupas",
            "external_aliases": ["short", "top"],
        },
        "esportes": {
            "display_name": "Esportes",
            "external_aliases": ["academia", "treino", "conjunto"],
        },
    }
    promotion = _promo(
        "Conjunto Suplex Feminino Top e Short Cintura Alta "
        "- Cinza e Preto Treino e Academia",
        source="shopee",
    )
    assert resolve_category(promotion, categories) == "esportes"


def test_exclude_keywords_skip_category():
    categories = {
        "eletronicos": {
            "display_name": "Eletrônicos",
            "external_aliases": ["impressora"],
            "exclude_keywords": ["impressora 3d", "resina"],
        }
    }
    promotion = _promo("Resina para impressora 3d anycubic")
    assert resolve_category(promotion, categories) == "geral"


def test_live_pelucia_not_roupas():
    title = (
        "30cm gigante bonito tubarão brinquedo de pelúcia macio recheado "
        "speelgoed animal almofada boneca presente para crianças"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "geral"


def test_live_swim_jammer_is_esportes():
    title = (
        "MY KILOMETRE Jammer de maiô masculino Maiô de treinamento atlético "
        "Calções de banho de competição Roupa de banho masculina Swim Jammers"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "esportes"


def test_live_phone_case_moda_is_eletronicos():
    title = (
        "Para poco m5s caso poco m5 caso de telefone poco f3 moda capa macia"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "eletronicos"


def test_live_jewelry_polish_cloth_is_casa():
    title = (
        "10/50pc prata polonês pano de limpeza macio toalhetes para talheres "
        "ouro jóias ferramenta"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "casa"


def test_live_iem_palco_not_games():
    title = (
        "Epyx pro-sistema de controle sem fio ptm-10, estéreo, in-ear, palco, "
        "retorno, corpo, receptor, sistema iem, 900mhz/500mhz"
    )
    promo = _promo(title, final_price=100.0, affiliate_url="https://a")
    assert resolve_category(promo, LIVE_CATEGORIES) != "games"
    approved, reasons = apply_promotion_rules(promo, LIVE_RULES)
    assert not approved
    assert any("blocked keyword" in reason for reason in reasons)


def test_live_arduino_encoder_blocked():
    title = (
        "Novo módulo codificador rotativo KY-040 com botão de pressão "
        "para arduino volume menu controle do motor"
    )
    promo = _promo(title, final_price=20.0, affiliate_url="https://a")
    approved, reasons = apply_promotion_rules(promo, LIVE_RULES)
    assert not approved
    assert any("blocked keyword" in reason for reason in reasons)


def test_live_genshin_plush_is_games():
    title = (
        "1pc 35/45cm genshin impacto pelúcia slime travesseiro brinquedos "
        "genshin impacto elemental slime almofada de pelúcia plushie"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "games"


def test_live_anime_action_figure_is_games():
    title = (
        "Dragon Ball Z Anime Action Figure Set, Super Saiyajin, Goku Filho, "
        "Gohan, Vegeta, Broly, Piccolo, Majin Buu, Model Toy Gifts"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "games"


def test_live_ventilador_mesa_is_casa():
    title = (
        "Ventilador De Mesa Arno Air Force Va46 40cm 6 Pás 3 Velocidades"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "casa"


def test_live_cooler_master_fan_is_games():
    title = "Cooler Fan, Cooler Master Mf120 Halo V2, Argb, White, 120mm"
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "games"


def test_live_mesa_escritorio_is_moveis():
    title = "Mesa Para Escritório Madesa, Preto - 9409"
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "moveis"


def test_live_camera_cage_not_roupas():
    title = (
        "Smallrig dslr câmera gaiola rig para sony a6400 com alça de silicone "
        "& sapato frio para sony a6100/a6300/a6400 câmera 3164"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "eletronicos"


def test_live_tripod_boom_not_roupas():
    title = (
        "Vijim ls02 ls08 estender c tripé braçadeira 90cm suporte de mesa "
        "ao vivo boom braço bola cabeça para anel luz slr smartphone gopro"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "eletronicos"


def test_live_apple_watch_band_is_eletronicos():
    title = (
        "Pulseira de aço inoxidável para apple relógio banda 44mm "
        "pulseira de metal iwatch série 7 se ultra 8"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "eletronicos"


def test_live_privacy_panel_not_beleza():
    title = (
        "Painel de privacidade metálico para exterior Divisória Decorativa "
        "para Ambientes, Protetor Solar, Resistente às Intempéries"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "casa"


def test_live_headlamp_not_veiculos():
    title = (
        "Acebeam H30 Farol Ultra Brilhante 4000 Lumens USB-C Farol Recarregável"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) != "veiculos"


def test_live_pyrite_specimen_blocked():
    title = (
        "Natural de alta densidade pirita cúbica pedra tolo ouro áspero "
        "irregular minério mineral ensino espécime ornamentos"
    )
    promo = _promo(title, final_price=10.0, affiliate_url="https://a")
    approved, reasons = apply_promotion_rules(promo, LIVE_RULES)
    assert not approved
    assert any("blocked keyword" in reason for reason in reasons)


def test_live_hario_dripper_not_games():
    title = "HARIO SSD-200-B Gotejador por imersão Switch Preto Direto do Japão"
    assert resolve_category(_promo(title), LIVE_CATEGORIES) in {"casa", "alimentos"}


def test_live_dark_lab_creatina_is_esportes():
    assert (
        resolve_category(_promo("Creatina Monohidratada Dark Lab 300g"), LIVE_CATEGORIES)
        == "esportes"
    )


def test_model_code_ssd_does_not_match_bare_ssd():
    from app.category_resolver import _find_alias_span

    assert _find_alias_span("HARIO SSD-200-B Gotejador", "ssd") is None
    assert _find_alias_span("SSD NVMe 1TB", "ssd") is not None


def test_live_industrial_joystick_blocked():
    title = (
        "Controle Industrial com Joystick de 4 Posições e Alavanca Cruzada "
        "para Guincho e Talha"
    )
    promo = _promo(title, final_price=50.0, affiliate_url="https://a")
    assert resolve_category(promo, LIVE_CATEGORIES) != "games"
    approved, reasons = apply_promotion_rules(promo, LIVE_RULES)
    assert not approved
    assert any("blocked keyword" in reason for reason in reasons)


def test_live_pijama_botao_adulto_not_blocked():
    title = (
        "Pijama Blogueirinha Baby Doll Feminino Botão Adulto Americano "
        "Pós Cirúrgico"
    )
    promo = _promo(
        title,
        source="shopee",
        final_price=29.96,
        price=38.91,
        discount_percentage=23.0,
        affiliate_url="https://a",
        sales=200,
        rating=4.5,
    )
    resolve_category(promo, LIVE_CATEGORIES)
    approved, reasons = apply_promotion_rules(promo, LIVE_RULES)
    assert approved, reasons


def test_live_fone_de_ouvido_bluetooth_high_intent():
    title = "Fone de Ouvido Bluetooth Sem Fio J760 com cancelamento de ruído"
    promo = _promo(
        title,
        source="shopee",
        final_price=50.33,
        price=71.90,
        discount_percentage=30.0,
        affiliate_url="https://a",
    )
    resolve_category(promo, LIVE_CATEGORIES)
    approved, reasons = apply_promotion_rules(promo, LIVE_RULES)
    assert approved, reasons


def test_live_bone_nike_is_roupas():
    assert (
        resolve_category(_promo("Boné Nike aba curva masculino"), LIVE_CATEGORIES)
        == "roupas"
    )


def test_live_pcp_compressor_not_games():
    title = (
        "TUXING 4500Psi 300Bar Compressor de ar PCP Display LCD "
        "Sistema de controle digital"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "geral"


def test_live_lab_psu_not_games():
    title = (
        "Ajustar fonte de alimentação dc fonte de alimentação de bancada "
        "de laboratório ajustável 30v 10a"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "geral"


def test_live_printer_3d_is_eletronicos():
    title = "ANYCUBIC DLP SLA LCD Impressora 3D de resina Photon Mono"
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "eletronicos"


def test_live_controle_xbox_is_games():
    assert (
        resolve_category(_promo("Controle Xbox Series X sem fio"), LIVE_CATEGORIES)
        == "games"
    )


def test_live_fonte_atx_is_games():
    assert (
        resolve_category(_promo("Fonte ATX 650W 80 Plus para gabinete"), LIVE_CATEGORIES)
        == "games"
    )


def test_live_mousepad_gamer_is_games():
    assert (
        resolve_category(_promo("Mousepad Gamer Redragon Flick L P031"), LIVE_CATEGORIES)
        == "games"
    )


def test_live_stream_deck_is_games():
    assert (
        resolve_category(
            _promo("Mesa Controladora Streaming Elgato Stream Deck Neo"),
            LIVE_CATEGORIES,
        )
        == "games"
    )


def test_live_notebook_comum_is_eletronicos():
    assert (
        resolve_category(
            _promo("Notebook Lenovo IdeaPad 1 AMD Ryzen 5 7520U 8GB 512GB SSD"),
            LIVE_CATEGORIES,
        )
        == "eletronicos"
    )


def test_live_apple_watch_is_eletronicos():
    assert (
        resolve_category(
            _promo("Apple Watch Se 3 Gps Caixa Estelar De Alumínio De 40 Mm"),
            LIVE_CATEGORIES,
        )
        == "eletronicos"
    )


def test_live_perfume_automotivo_is_veiculos():
    assert (
        resolve_category(
            _promo("Perfume Automotivo Legacy Elixir By V8 Intense Para Carros"),
            LIVE_CATEGORIES,
        )
        == "veiculos"
    )


def test_live_perfume_comum_is_beleza():
    assert (
        resolve_category(_promo("Perfume feminino 100ml eau de parfum"), LIVE_CATEGORIES)
        == "beleza"
    )


def test_live_mesa_digitalizadora_is_eletronicos():
    assert (
        resolve_category(
            _promo("Mesa Digitalizadora Huion Kamvas 13 Usb Cosmo Black"),
            LIVE_CATEGORIES,
        )
        == "eletronicos"
    )


def test_live_thunderx3_chair_is_games():
    assert (
        resolve_category(
            _promo("Cadeira Office Thunderx3 Xtc Mesh Até 150kg Reclinável"),
            LIVE_CATEGORIES,
        )
        == "games"
    )


def test_live_termovisor_not_eletronicos():
    title = (
        "Mileseey tr120 termovisor profissional câmera térmica "
        "infravermelha de alta resolução"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "geral"


def test_live_wd_purple_is_eletronicos():
    assert (
        resolve_category(
            _promo("Hd Wd 2tb Purple Surveillance Sata Iii 5400 Rpm"),
            LIVE_CATEGORIES,
        )
        == "eletronicos"
    )


def test_live_headphone_case_not_moda():
    title = (
        "Bolsa de Luxo Universal para Fones de Ouvido, Estojo de Couro Real "
        "para Fones Bluetooth com Chaveiro, Bolsa de Armazenamento para Pequenos Itens"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "eletronicos"


def test_live_headphone_case_not_moda_even_with_store_category():
    title = (
        "Bolsa de Luxo Universal para Fones de Ouvido, Estojo de Couro Real "
        "para Fones Bluetooth com Chaveiro"
    )
    assert (
        resolve_category(_promo(title, category="moda"), LIVE_CATEGORIES)
        == "eletronicos"
    )


def test_live_kids_electric_car_not_games():
    title = (
        "Carro Elétrico Infantil Motor de Direção, Caixa de Engrenagens, "
        "Controle Remoto, Acessórios para Carrinho, RS280, 380, 390, 6V, 12V"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "geral"


def test_live_veiculos_pneu():
    assert resolve_category(_promo("Pneu aro 15 carro passeio"), LIVE_CATEGORIES) == (
        "veiculos"
    )


def test_live_bicicleta_disabled_from_esportes():
    assert (
        resolve_category(_promo("Bicicleta mountain bike aro 29"), LIVE_CATEGORIES)
        != "esportes"
    )


def test_live_cafe_is_alimentos():
    assert resolve_category(_promo("Café torrado em grãos 1kg"), LIVE_CATEGORIES) == (
        "alimentos"
    )


def test_live_whey_stays_esportes():
    assert resolve_category(_promo("Whey protein isolado 1kg"), LIVE_CATEGORIES) == (
        "esportes"
    )


def test_live_ceiling_light_goes_to_casa():
    title = (
        "Luminárias de teto modernas com LED NEO Gleam para sala de estar, "
        "quarto, escritório, AC90-260V"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "casa"


def test_live_abajur_goes_to_casa():
    assert resolve_category(_promo("Abajur de mesa LED para quarto"), LIVE_CATEGORIES) == (
        "casa"
    )


def test_live_power_inverter_not_eletronicos():
    title = (
        "Conversor de Energia, Transformador Solar, 12V, 24V, 220V, 110V, "
        "1000W, LED de onda senoidal pura, 12V do 220V"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "geral"


def test_blocked_power_inverter_spam():
    promo = _promo(
        "Conversor de Energia Transformador Solar onda senoidal pura 2000W",
        final_price=120.0,
        price=120.0,
        discount_percentage=20.0,
    )
    approved, reasons = apply_promotion_rules(promo, LIVE_RULES)
    assert approved is False
    assert any("blocked keyword" in reason for reason in reasons)


def test_live_cnc_stepper_not_veiculos():
    title = (
        "Nema23 57 Kit de motor deslizante, 4 eixos, CNC, 3Nm, "
        "Motor, Drivers, fonte de alimentação 36V, cartão MACH3"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "geral"


def test_live_nema_stepper_not_veiculos():
    title = (
        "Cloudray Nema 24 Kit de driver de motor de passo Loop aberto "
        "para impressora 3D Máquina fresadora CNC"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "geral"


def test_live_car_inverter_not_veiculos():
    title = (
        "Inversor 12v 220v 2000w potência carro micro inversor "
        "onda senoidal pura lcd"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "geral"


def test_live_moto_helmet_is_veiculos():
    assert (
        resolve_category(_promo("Capacete para moto fechado com viseira"), LIVE_CATEGORIES)
        == "veiculos"
    )


def test_live_diesel_engine_tool_is_veiculos():
    title = (
        "Barra de giro para motor, ferramenta de ajuste autônoma "
        "para motor diesel dd13 dd15"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "veiculos"


def test_live_car_seat_cover_is_veiculos():
    assert (
        resolve_category(_promo("Capa de banco couro para carro universal"), LIVE_CATEGORIES)
        == "veiculos"
    )


def test_live_car_mat_is_veiculos():
    assert (
        resolve_category(_promo("Tapete automotivo borracha kit 4 peças"), LIVE_CATEGORIES)
        == "veiculos"
    )


def test_live_moto_trunk_is_veiculos():
    assert (
        resolve_category(_promo("Baú moto 45 litros com base universal"), LIVE_CATEGORIES)
        == "veiculos"
    )


def test_live_vehicle_phone_mount_is_veiculos():
    assert (
        resolve_category(_promo("Suporte veicular magnético para celular"), LIVE_CATEGORIES)
        == "veiculos"
    )


def test_live_rear_camera_is_veiculos():
    assert (
        resolve_category(_promo("Câmera de ré com visão noturna"), LIVE_CATEGORIES)
        == "veiculos"
    )


def test_live_electric_scooter_is_veiculos():
    assert (
        resolve_category(_promo("Patinete elétrico dobrável 350W"), LIVE_CATEGORIES)
        == "veiculos"
    )


def test_live_smartphone_is_eletronicos():
    assert (
        resolve_category(_promo("Smartphone Samsung Galaxy A15 128GB"), LIVE_CATEGORIES)
        == "eletronicos"
    )


def test_live_smartwatch_is_eletronicos():
    assert (
        resolve_category(_promo("Smartwatch pulseira inteligente Xiaomi"), LIVE_CATEGORIES)
        == "eletronicos"
    )


def test_live_echo_dot_is_eletronicos():
    assert (
        resolve_category(_promo("Echo Dot 5ª geração Alexa"), LIVE_CATEGORIES)
        == "eletronicos"
    )


def test_live_fire_tv_is_eletronicos():
    assert (
        resolve_category(_promo("Fire TV Stick 4K streaming"), LIVE_CATEGORIES)
        == "eletronicos"
    )


def test_live_ssd_externo_is_eletronicos():
    assert (
        resolve_category(_promo("SSD externo portátil 1TB USB-C"), LIVE_CATEGORIES)
        == "eletronicos"
    )


def test_live_antena_digital_is_eletronicos():
    assert (
        resolve_category(_promo("Antena digital HDTV interna"), LIVE_CATEGORIES)
        == "eletronicos"
    )


def test_live_aparador_barba_is_eletronicos():
    assert (
        resolve_category(_promo("Aparador de barba elétrico Philips"), LIVE_CATEGORIES)
        == "eletronicos"
    )


def test_live_capacitor_clamp_not_eletronicos():
    title = (
        "5 pçs durável capacitor suporte braçadeira clap 30mm 35mm "
        "40mm 50mm 65mm 75mm 90mm clipe de montagem superfície "
        "chapeamento amplificador zinco"
    )
    assert resolve_category(_promo(title), LIVE_CATEGORIES) == "geral"


def test_live_amplificador_som_is_eletronicos():
    assert (
        resolve_category(
            _promo("Amplificador de som receiver home theater 200W"),
            LIVE_CATEGORIES,
        )
        == "eletronicos"
    )


def test_blocked_ophthalmic_instrument():
    promo = _promo(
        "Pinça de capsulorrexis retinal instrumentos micro cirúrgicos oftálmicos",
        final_price=50.0,
        price=50.0,
        discount_percentage=20.0,
    )
    approved, reasons = apply_promotion_rules(promo, LIVE_RULES)
    assert approved is False
    assert any("blocked keyword" in reason for reason in reasons)


def test_blocked_pcp_compressor():
    promo = _promo(
        "TUXING compressor pcp 4500psi bomba de alta pressão",
        final_price=200.0,
        price=200.0,
        discount_percentage=20.0,
    )
    approved, reasons = apply_promotion_rules(promo, LIVE_RULES)
    assert approved is False
    assert any("blocked keyword" in reason for reason in reasons)


def test_title_beats_api_category_for_switch_cover():
    promo = _promo(
        "2PCS Capas de Silicone para Controle Switch 2, Protetores "
        "Transparentes Antiderrapantes para Joystick, Acessórios para Switch 2",
        category="Laptop Accessories",
        tags=["Phone Accessories"],
    )
    assert resolve_category(promo, LIVE_CATEGORIES) == "games"


def test_title_beats_furniture_api_category_for_mousepad():
    promo = _promo(
        "Mousepad grande personalizado tapete de mesa para jogos de anime",
        category="Furniture",
        tags=["Office Furniture"],
    )
    assert resolve_category(promo, LIVE_CATEGORIES) == "games"


def test_nail_dryer_goes_to_beleza_not_eletronicos_or_casa():
    promo = _promo(
        "Secador de Unhas UV LED Flexível com Clip, Lâmpada de Mesa Mini "
        "Portátil USB para Manicure e Esmalte em Gel",
        category="Laptop Accessories",
        tags=["LED Lighting"],
    )
    assert resolve_category(promo, LIVE_CATEGORIES) == "beleza"


def test_word_boundary_avoids_bota_inside_bluetooth():
    promo = _promo(
        "Óculos inteligentes câmera ai hd wearable mini câmera bluetooth "
        "controle assistente de voz"
    )
    assert resolve_category(promo, LIVE_CATEGORIES) == "eletronicos"


def test_decoracao_does_not_beat_joystick_accessory():
    promo = _promo(
        "Joystick de Silicone Hello Kitty para PS5, acessórios para controle "
        "de jogo, decoração"
    )
    assert resolve_category(promo, LIVE_CATEGORIES) == "games"


def test_cpu_fan_pattern_is_blocked():
    promo = _promo(
        "Ventilador de cpu para laptop ventilador de refrigeração",
        final_price=40.0,
        price=40.0,
        discount_percentage=20.0,
    )
    approved, reasons = apply_promotion_rules(promo, LIVE_RULES)
    assert approved is False
    assert any("blocked keyword" in reason for reason in reasons)


def test_ignition_switch_goes_to_veiculos_not_esportes():
    promo = _promo(
        "Universal Ignição Interruptor para Auto Motocross Bicicleta Elétrica Scooter"
    )
    assert resolve_category(promo, LIVE_CATEGORIES) == "veiculos"


def test_motorola_radio_battery_not_veiculos():
    promo = _promo(
        "Bateria recarregável USB tipo C para Motorola R7 rádio em dois sentidos"
    )
    assert resolve_category(promo, LIVE_CATEGORIES) == "eletronicos"


def test_pixel_led_panel_goes_to_eletronicos():
    promo = _promo(
        "Painel de luz led com controle bluetooth display programável "
        "decoração de mesa lâmpada inteligente de tela de pixel"
    )
    assert resolve_category(promo, LIVE_CATEGORIES) == "eletronicos"


def test_shampoo_automotivo_goes_to_veiculos():
    assert (
        resolve_category(
            _promo("Shampoo automotivo concentrado limpeza para carro"),
            LIVE_CATEGORIES,
        )
        == "veiculos"
    )


def test_controle_sem_fio_ps5_accumulates_independent_evidence():
    assert (
        resolve_category(
            _promo("Controle sem fio para PS5"),
            LIVE_CATEGORIES,
        )
        == "games"
    )


def test_mesa_gamer_ps5_prefers_games_over_moveis():
    assert (
        resolve_category(
            _promo("Mesa gamer com suporte para controle PS5"),
            LIVE_CATEGORIES,
        )
        == "games"
    )


def test_nested_alias_does_not_inflate_score():
    title = "Lanterna tática militar recarregável"
    base_aliases = [
        "lanterna tatica",
        "lanterna tática",
        "lanterna recarregavel",
        "lanterna recarregável",
    ]
    nested_aliases = [*base_aliases, "lanterna", "led"]

    score_without = _rank_categories(
        title,
        [],
        {"eletronicos": {"external_aliases": base_aliases}},
    )[0][1]
    score_with_nested = _rank_categories(
        title,
        [],
        {"eletronicos": {"external_aliases": nested_aliases}},
    )[0][1]

    assert score_with_nested == score_without
