from fastapi import APIRouter

router = APIRouter(tags=['health'])


@router.get('/health')
def health() -> dict:
    return {'success': True, 'data': {'status': 'ok'}, 'message': 'Backend operativo'}
