import math


def haversine(lat1, lon1, lat2, lon2, radius=6371.0):
    """Return great-circle distance between two points on Earth (in kilometers by default)."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c


if __name__ == "__main__":
    # Example usage
    nyc = (40.7128, -74.0060)
    london = (51.5074, -0.1278)
    print(f"Distance: {haversine(*nyc, *london):.2f} km")
