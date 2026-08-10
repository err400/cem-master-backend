def sample_spot(**overrides):
    spot = {
        "source_project_id": "sanjay-van",
        "source_spot_id": "s1",
        "name": "Sanjay Van Site 1",
        "description": "Sample monitoring location",
        "latitude": 28.533,
        "longitude": 77.176,
    }
    spot.update(overrides)
    return spot


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_spot(client):
    response = client.post("/api/v1/spots", json=sample_spot())

    assert response.status_code == 201
    data = response.json()
    assert data["id"] == 1
    assert data["name"] == "Sanjay Van Site 1"


def test_duplicate_rejected(client):
    assert client.post("/api/v1/spots", json=sample_spot()).status_code == 201

    response = client.post("/api/v1/spots", json=sample_spot(name="Duplicate name"))

    assert response.status_code == 409
    assert response.json()["detail"] == "Spot already exists"


def test_spots_geojson_output(client):
    assert client.post("/api/v1/spots", json=sample_spot()).status_code == 201

    response = client.get("/api/v1/spots")

    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1
    feature = data["features"][0]
    assert feature["type"] == "Feature"
    assert feature["geometry"] == {"type": "Point", "coordinates": [77.176, 28.533]}
    assert feature["properties"]["source_project_id"] == "sanjay-van"
    assert feature["properties"]["source_spot_id"] == "s1"
    assert feature["properties"]["name"] == "Sanjay Van Site 1"


def test_empty_spots_geojson(client):
    response = client.get("/api/v1/spots")

    assert response.status_code == 200
    assert response.json() == {"type": "FeatureCollection", "features": []}


def test_invalid_coordinates_rejected(client):
    response = client.post("/api/v1/spots", json=sample_spot(latitude=91))

    assert response.status_code == 422


def test_blank_required_fields_rejected(client):
    response = client.post("/api/v1/spots", json=sample_spot(name="   "))

    assert response.status_code == 422
