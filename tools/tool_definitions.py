"""
Tool schemas passed to the Claude API for the Intelligence Agent.
Claude uses these definitions to decide when and how to call each tool.
"""

INTELLIGENCE_TOOLS = [
    {
        "name": "get_weather",
        "description": (
            "Get day-by-day weather forecast for a hiking route using NOAA/NWS. "
            "Returns temperature, precipitation chance, wind, and risk level per day. "
            "Also returns any active weather alerts for the area."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {
                    "type": "number",
                    "description": "Trailhead latitude"
                },
                "longitude": {
                    "type": "number",
                    "description": "Trailhead longitude"
                },
                "start_date": {
                    "type": "string",
                    "description": "Trip start date in YYYY-MM-DD format"
                },
                "end_date": {
                    "type": "string",
                    "description": "Trip end date in YYYY-MM-DD format"
                }
            },
            "required": ["latitude", "longitude", "start_date", "end_date"]
        }
    },
    {
        "name": "get_air_quality",
        "description": (
            "Get AQI forecast for a hiking route using EPA AirNow. "
            "Returns AQI value, category, and risk level per day. "
            "AQI > 150 is considered high risk for this system."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {
                    "type": "number",
                    "description": "Trailhead latitude"
                },
                "longitude": {
                    "type": "number",
                    "description": "Trailhead longitude"
                },
                "start_date": {
                    "type": "string",
                    "description": "Trip start date in YYYY-MM-DD format"
                },
                "end_date": {
                    "type": "string",
                    "description": "Trip end date in YYYY-MM-DD format"
                }
            },
            "required": ["latitude", "longitude", "start_date", "end_date"]
        }
    },
    {
        "name": "get_fire_data",
        "description": (
            "Check for active wildfire perimeters near a hiking route using NIFC. "
            "Returns list of nearby fires and the distance to the closest fire. "
            "Fire within 5 miles = high risk, 5-15 miles = medium risk, >15 miles = low risk."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "min_lat": {
                    "type": "number",
                    "description": "Bounding box minimum latitude"
                },
                "max_lat": {
                    "type": "number",
                    "description": "Bounding box maximum latitude"
                },
                "min_lon": {
                    "type": "number",
                    "description": "Bounding box minimum longitude"
                },
                "max_lon": {
                    "type": "number",
                    "description": "Bounding box maximum longitude"
                },
                "trailhead_lat": {
                    "type": "number",
                    "description": "Trailhead latitude for distance calculations"
                },
                "trailhead_lon": {
                    "type": "number",
                    "description": "Trailhead longitude for distance calculations"
                }
            },
            "required": ["min_lat", "max_lat", "min_lon", "max_lon", "trailhead_lat", "trailhead_lon"]
        }
    },
    {
        "name": "get_wildlife",
        "description": (
            "Get recent bear and cougar sightings near a hiking route using iNaturalist. "
            "Queries research-grade observations within the route bounding box over the past 30 days. "
            "Returns sighting counts, risk level, and notes on wildlife activity."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "min_lat": {
                    "type": "number",
                    "description": "Bounding box minimum latitude"
                },
                "max_lat": {
                    "type": "number",
                    "description": "Bounding box maximum latitude"
                },
                "min_lon": {
                    "type": "number",
                    "description": "Bounding box minimum longitude"
                },
                "max_lon": {
                    "type": "number",
                    "description": "Bounding box maximum longitude"
                }
            },
            "required": ["min_lat", "max_lat", "min_lon", "max_lon"]
        }
    },
    {
        "name": "get_streamflow",
        "description": (
            "Get current streamflow conditions at river crossings along a hiking route using USGS. "
            "Finds the nearest gauge station to each crossing and returns current flow in CFS. "
            "High flow = dangerous crossing. Returns risk level per crossing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "crossings": {
                    "type": "array",
                    "description": "List of water crossings along the route",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "lat": {"type": "number"},
                            "lon": {"type": "number"}
                        },
                        "required": ["name", "lat", "lon"]
                    }
                }
            },
            "required": ["crossings"]
        }
    }
]
