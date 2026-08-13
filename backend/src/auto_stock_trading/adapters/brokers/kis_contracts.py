from typing import ClassVar

from pydantic import BaseModel, ConfigDict, SecretStr


class KisContract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)


class KisTokenResponse(KisContract):
    access_token: SecretStr
    token_type: str
    expires_in: int
    access_token_token_expired: str


class KisInstrumentOutput(KisContract):
    pdno: str
    prdt_type_cd: str
    prdt_name: str
    prdt_eng_name: str = ""
    mket_id_cd: str
    etf_dvsn_cd: str = ""
    scts_mket_lstg_dt: str = ""
    scts_mket_lstg_abol_dt: str = ""
    kosdaq_mket_lstg_dt: str = ""
    kosdaq_mket_lstg_abol_dt: str = ""
    lstg_abol_dt: str = ""
    tr_stop_yn: str = "N"


class KisInstrumentResponse(KisContract):
    rt_cd: str
    msg_cd: str
    msg1: str
    output: KisInstrumentOutput


class KisQuoteOutput(KisContract):
    stck_prpr: str
    stck_oprc: str
    stck_hgpr: str
    stck_lwpr: str
    stck_sdpr: str
    prdy_vrss: str
    prdy_ctrt: str
    acml_vol: str
    acml_tr_pbmn: str


class KisQuoteResponse(KisContract):
    rt_cd: str
    msg_cd: str
    msg1: str
    output: KisQuoteOutput


class KisDailySummary(KisContract):
    stck_shrn_iscd: str = ""
    hts_kor_isnm: str = ""


class KisDailyBarOutput(KisContract):
    stck_bsop_date: str
    stck_oprc: str
    stck_hgpr: str
    stck_lwpr: str
    stck_clpr: str
    acml_vol: str
    acml_tr_pbmn: str
    mod_yn: str = "N"
    prtt_rate: str = ""
    revl_issu_reas: str = ""


class KisDailyBarsResponse(KisContract):
    rt_cd: str
    msg_cd: str
    msg1: str
    output1: KisDailySummary
    output2: tuple[KisDailyBarOutput, ...]
