"""
Venue adapters - Concrete implementations of IVenueAdapter

Supported venues:
- gTrade: Primary venue (market-based perpetuals)
- Ostium: Legacy venue (kept for backward compatibility)

Each venue has its own folder with:
- Adapter implementation (IVenueAdapter)
- Models/mappers (venue-specific to domain)
- Configuration
"""
