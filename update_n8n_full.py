import httpx

headers = {
    'X-N8N-API-KEY': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI1YjYxMWZkZC00NWVmLTRhMTMtYTQ5OS0xOGQ1MmVjMzg2ZmYiLCJpc3MiOiJuOG4iLCJhdWQiOiJwdWJsaWMtYXBpIiwianRpIjoiNjg5MzgxMjctNGQ5Yy00MTYzLWI1MWEtYjBlMzk1YjRiNWM5IiwiaWF0IjoxNzkwMTAzNzY2LCJleHAiOjE3OTI2MzgwMDB9.Yst7jcezSKCZb4aHGf8bj_QfYIBqRL88SL0JaAOKts8'
}

wf_id = 'RYdbEYlZmpN2vgl3'

workflow = {
    'name': 'Catalogo 3D - Notificacao WhatsApp & Postgres',
    'nodes': [
        {
            'parameters': {
                'httpMethod': 'POST',
                'path': 'catalogo-pedido',
                'responseMode': 'responseNode',
                'options': {}
            },
            'id': 'e6741b0b-c8c3-4d6d-88b1-9f2cb42b8e30',
            'name': 'Webhook Pedido',
            'type': 'n8n-nodes-base.webhook',
            'typeVersion': 2,
            'position': [240, 300],
            'webhookId': 'catalogo-pedido'
        },
        {
            'parameters': {
                'operation': 'executeQuery',
                'query': "=INSERT INTO orders (model_id, model_title, customer_name, customer_phone, customer_notes, price_registered, show_price) VALUES ({{ $json.body.model.id || 1 }}, '{{ $json.body.model.title }}', '{{ $json.body.customer.name }}', '{{ $json.body.customer.phone }}', '{{ $json.body.customer.notes }}', {{ $json.body.model.price || 0 }}, {{ $json.body.model.show_price ? 'true' : 'false' }}) RETURNING id;",
                'options': {}
            },
            'id': '77777777-c8c3-4d6d-88b1-9f2cb42b8e30',
            'name': 'Postgres Salvar Pedido',
            'type': 'n8n-nodes-base.postgres',
            'typeVersion': 2.6,
            'position': [480, 300],
            'credentials': {
                'postgres': {
                    'id': 'oCuh5zMwf2r59gJ6',
                    'name': 'Postgres_Catalogo3D'
                }
            },
            'continueOnFail': True
        },
        {
            'parameters': {
                'method': 'POST',
                'url': 'https://evowsapi.3afieldservice.com.br/message/sendMedia/andre',
                'sendHeaders': True,
                'headerParameters': {
                    'parameters': [
                        {
                            'name': 'apikey',
                            'value': '4eddc4b3-5499-47a1-9b8b-d4afa9ad00e8'
                        },
                        {
                            'name': 'Content-Type',
                            'value': 'application/json'
                        }
                    ]
                },
                'sendBody': True,
                'specifyBody': 'json',
                'jsonBody': "={{ JSON.stringify({\n  number: $('Webhook Pedido').item.json.body.whatsapp_dest,\n  mediatype: 'image',\n  mimetype: 'image/jpeg',\n  caption: $('Webhook Pedido').item.json.body.message,\n  media: $('Webhook Pedido').item.json.body.image_url,\n  fileName: (($('Webhook Pedido').item.json.body.model.title || 'modelo') + '.jpg')\n}) }}",
                'options': {}
            },
            'id': '11904a43-0c4a-4ff1-b847-8149d5bf1c42',
            'name': 'Evolution API - Enviar WhatsApp',
            'type': 'n8n-nodes-base.httpRequest',
            'typeVersion': 4.2,
            'position': [720, 300],
            'continueOnFail': True
        },
        {
            'parameters': {
                'respondWith': 'json',
                'responseBody': '={\n  "ok": true,\n  "message": "Pedido registrado no PostgreSQL e notificação enviada ao WhatsApp com sucesso"\n}',
                'options': {}
            },
            'id': 'acfa8122-3837-4f67-a066-b25055018693',
            'name': 'Responder Webhook',
            'type': 'n8n-nodes-base.respondToWebhook',
            'typeVersion': 1.1,
            'position': [960, 300]
        }
    ],
    'connections': {
        'Webhook Pedido': {
            'main': [
                [
                    {
                        'node': 'Postgres Salvar Pedido',
                        'type': 'main',
                        'index': 0
                    }
                ]
            ]
        },
        'Postgres Salvar Pedido': {
            'main': [
                [
                    {
                        'node': 'Evolution API - Enviar WhatsApp',
                        'type': 'main',
                        'index': 0
                    }
                ]
            ]
        },
        'Evolution API - Enviar WhatsApp': {
            'main': [
                [
                    {
                        'node': 'Responder Webhook',
                        'type': 'main',
                        'index': 0
                    }
                ]
            ]
        }
    },
    'settings': {
        'executionOrder': 'v1'
    }
}

httpx.post(f'https://editoncst.3afieldservice.com.br/api/v1/workflows/{wf_id}/deactivate', headers=headers)
r_put = httpx.put(f'https://editoncst.3afieldservice.com.br/api/v1/workflows/{wf_id}', headers=headers, json=workflow, timeout=10)
print('PUT STATUS:', r_put.status_code)
r_act = httpx.post(f'https://editoncst.3afieldservice.com.br/api/v1/workflows/{wf_id}/activate', headers=headers, timeout=10)
print('ACTIVATE STATUS:', r_act.status_code)
