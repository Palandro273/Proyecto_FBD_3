from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from datetime import datetime
from bson import ObjectId
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

client = MongoClient(os.environ["MONGO_URI"])
db = client["ISIS2304H03202610"]


@app.get("/")
def inicio():
    return {"estado": "API funcionando correctamente"}


def serializar(doc: dict) -> dict:
    doc["_id"] = str(doc["_id"])
    return doc


@app.post("/resenas")
def crear_resena(datos: dict):
    existe = db.resenas.find_one({"id_reserva": datos["id_reserva"]})
    if existe:
        return {"error": "Ya existe una reseña para esta reserva"}

    datos["id_reserva"]     = int(datos["id_reserva"])
    datos["id_hotel"]       = int(datos["id_hotel"])
    datos["id_cliente"]     = int(datos["id_cliente"])
    datos["calificacion"]   = int(datos["calificacion"])
    datos["fecha_creacion"] = datetime.now()
    datos["estado"]         = "publicada"
    datos["destacada"]      = False
    datos["util_count"]     = 0
    datos["respuesta_admin"] = None

    db.resenas.insert_one(datos)
    return {"mensaje": "Reseña creada"}


@app.put("/resenas/{id_resena}")
def editar_resena(id_resena: str, datos: dict):
    db.resenas.update_one(
        {"_id": ObjectId(id_resena)},
        {"$set": {
            "calificacion": int(datos["calificacion"]),
            "texto":        datos["texto"]
        }}
    )
    return {"mensaje": "Reseña actualizada"}


@app.delete("/resenas/{id_resena}")
def eliminar_resena(id_resena: str):
    db.resenas.update_one(
        {"_id": ObjectId(id_resena)},
        {"$set": {"estado": "eliminada"}}
    )
    return {"mensaje": "Reseña eliminada"}


@app.get("/hoteles/{id_hotel}/resenas")
def consultar_resenas_hotel(id_hotel: int, orden: str = "fecha", pagina: int = 1, por_pagina: int = 10):
    campo_orden = "fecha_creacion" if orden == "fecha" else "util_count"
    skip = (pagina - 1) * por_pagina

    destacada = db.resenas.find_one({"id_hotel": id_hotel, "estado": "publicada", "destacada": True})

    cursor = db.resenas.find(
        {"id_hotel": id_hotel, "estado": "publicada", "destacada": {"$ne": True}}
    ).sort(campo_orden, -1).skip(skip).limit(por_pagina)

    resenas = []
    if destacada:
        resenas.append(serializar(destacada))
    for r in cursor:
        resenas.append(serializar(r))

    return resenas


@app.post("/resenas/{id_resena}/votos")
def votar_resena(id_resena: str, datos: dict):
    id_usuario = int(datos["id_usuario"])

    existe = db.votos.find_one({"id_resena": ObjectId(id_resena), "id_usuario": id_usuario})
    if existe:
        return {"error": "Ya votaste por esta reseña"}

    db.votos.insert_one({
        "id_resena":  ObjectId(id_resena),
        "id_usuario": id_usuario,
        "fecha":      datetime.now()
    })
    db.resenas.update_one({"_id": ObjectId(id_resena)}, {"$inc": {"util_count": 1}})
    return {"mensaje": "Voto registrado"}


@app.get("/clientes/{id_cliente}/resenas")
def historial_resenas(id_cliente: int, orden: str = "fecha"):
    campo_orden = "fecha_creacion" if orden == "fecha" else "id_hotel"
    cursor = db.resenas.find({"id_cliente": id_cliente}).sort(campo_orden, -1)
    return [serializar(r) for r in cursor]


@app.put("/resenas/{id_resena}/respuesta")
def responder_resena(id_resena: str, datos: dict):
    db.resenas.update_one(
        {"_id": ObjectId(id_resena)},
        {"$set": {
            "respuesta_admin": {
                "texto":    datos["texto"],
                "fecha":    datetime.now(),
                "id_admin": int(datos["id_admin"])
            }
        }}
    )
    return {"mensaje": "Respuesta registrada"}


@app.delete("/resenas/{id_resena}/admin")
def eliminar_resena_admin(id_resena: str):
    db.resenas.update_one(
        {"_id": ObjectId(id_resena)},
        {"$set": {"estado": "eliminada"}}
    )
    return {"mensaje": "Reseña eliminada por administrador"}


@app.put("/resenas/{id_resena}/destacar")
def destacar_resena(id_resena: str, datos: dict):
    id_hotel = int(datos["id_hotel"])
    db.resenas.update_many(
        {"id_hotel": id_hotel, "destacada": True},
        {"$set": {"destacada": False}}
    )
    db.resenas.update_one(
        {"_id": ObjectId(id_resena)},
        {"$set": {"destacada": True}}
    )
    return {"mensaje": "Reseña destacada"}


@app.get("/consultas/top-hoteles")
def top_hoteles(fecha_ini: str, fecha_fin: str):
    pipeline = [
        {"$match": {
            "estado": "publicada",
            "fecha_creacion": {
                "$gte": datetime.fromisoformat(fecha_ini),
                "$lte": datetime.fromisoformat(fecha_fin + "T23:59:59")
            }
        }},
        {"$group": {
            "_id": "$id_hotel",
            "promedio_calificacion": {"$avg": "$calificacion"},
            "total_resenas": {"$sum": 1}
        }},
        {"$sort": {"promedio_calificacion": -1}},
        {"$limit": 10}
    ]
    return list(db.resenas.aggregate(pipeline))


@app.get("/consultas/evolucion/{id_hotel}")
def evolucion_hotel(id_hotel: int, anio: int):
    pipeline = [
        {"$match": {
            "id_hotel": id_hotel,
            "estado":   "publicada",
            "fecha_creacion": {
                "$gte": datetime(anio, 1, 1),
                "$lt":  datetime(anio + 1, 1, 1)
            }
        }},
        {"$group": {
            "_id": {"mes": {"$month": "$fecha_creacion"}},
            "promedio_calificacion": {"$avg": "$calificacion"},
            "total_resenas": {"$sum": 1}
        }},
        {"$sort": {"_id.mes": 1}}
    ]
    return list(db.resenas.aggregate(pipeline))


@app.get("/consultas/comparativo")
def comparativo_ciudad(ids_hoteles: str):
    ids = [int(x) for x in ids_hoteles.split(",")]
    pipeline = [
        {"$match": {
            "id_hotel": {"$in": ids},
            "estado":   "publicada"
        }},
        {"$group": {
            "_id": "$id_hotel",
            "promedio_calificacion": {"$avg": "$calificacion"},
            "total_resenas":         {"$sum": 1},
            "con_respuesta": {"$sum": {"$cond": [{"$ifNull": ["$respuesta_admin", False]}, 1, 0]}},
            "destacadas":    {"$sum": {"$cond": ["$destacada", 1, 0]}}
        }},
        {"$project": {
            "_id": 1,
            "promedio_calificacion": {"$round": ["$promedio_calificacion", 2]},
            "total_resenas": 1,
            "pct_con_respuesta": {"$round": [{"$multiply": [{"$divide": ["$con_respuesta", "$total_resenas"]}, 100]}, 2]},
            "pct_destacadas":    {"$round": [{"$multiply": [{"$divide": ["$destacadas",    "$total_resenas"]}, 100]}, 2]}
        }},
        {"$sort": {"promedio_calificacion": -1}}
    ]
    return list(db.resenas.aggregate(pipeline))