from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from auto_stock_trading.domain.market_data.adjustment_datasets import (
        AdjustedBarRecord,
        AdjustmentDatasetRecord,
        DatasetActionRecord,
    )
    from auto_stock_trading.domain.market_data.adjustments import AdjustmentMethod
    from auto_stock_trading.domain.market_data.corporate_actions import (
        CorporateActionRange,
        VersionedCorporateAction,
    )


class CorporateActionReader(Protocol):
    async def read_current(
        self,
        query: CorporateActionRange,
    ) -> tuple[VersionedCorporateAction, ...]: ...

    async def read_history(
        self,
        query: CorporateActionRange,
    ) -> tuple[VersionedCorporateAction, ...]: ...

    async def read_as_of(
        self,
        query: CorporateActionRange,
        knowledge_cutoff_at: datetime,
    ) -> tuple[VersionedCorporateAction, ...]: ...

    async def close(self) -> None: ...


class AdjustedPriceReader(Protocol):
    async def read_dataset(self, dataset_id: UUID) -> AdjustmentDatasetRecord | None: ...

    async def read_latest_published(
        self,
        symbol: str,
        method: AdjustmentMethod,
    ) -> AdjustmentDatasetRecord | None: ...

    async def read_datasets_for_action(
        self,
        action_key: UUID,
    ) -> tuple[AdjustmentDatasetRecord, ...]: ...

    async def read_adjusted_bars(self, dataset_id: UUID) -> tuple[AdjustedBarRecord, ...]: ...

    async def read_dataset_actions(self, dataset_id: UUID) -> tuple[DatasetActionRecord, ...]: ...

    async def close(self) -> None: ...
