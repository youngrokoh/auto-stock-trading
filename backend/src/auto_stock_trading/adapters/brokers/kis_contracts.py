from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


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


class KisMinuteSummary(KisContract):
    hts_kor_isnm: str = ""
    stck_prdy_clpr: str = ""
    acml_vol: str = ""


class KisMinuteBarOutput(KisContract):
    stck_bsop_date: str
    stck_cntg_hour: str
    stck_oprc: str
    stck_hgpr: str
    stck_lwpr: str
    stck_prpr: str
    cntg_vol: str
    acml_tr_pbmn: str


class KisMinuteBarsResponse(KisContract):
    rt_cd: str
    msg_cd: str
    msg1: str
    output1: KisMinuteSummary
    output2: tuple[KisMinuteBarOutput, ...]


class KisHolidayOutput(KisContract):
    bass_dt: Annotated[str, Field(pattern=r"^\d{8}$")]
    wday_dvsn_cd: str
    bzdy_yn: Literal["Y", "N"]
    tr_day_yn: Literal["Y", "N"]
    opnd_yn: Literal["Y", "N"]
    sttl_day_yn: Literal["Y", "N"]


class KisHolidayResponse(KisContract):
    rt_cd: str
    msg_cd: str
    msg1: str
    ctx_area_fk: str = ""
    ctx_area_nk: str = ""
    output: Annotated[tuple[KisHolidayOutput, ...], Field(min_length=1)]
