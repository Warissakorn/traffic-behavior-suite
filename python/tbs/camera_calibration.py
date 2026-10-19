"""Planar pixel-to-metre calibration from measured ground control points."""
import numpy as np


def camera_matrix(camera):
    if not isinstance(camera, dict) or camera.get('projection') != 'planar_homography':
        raise ValueError('Camera projection ต้องเป็น planar_homography')
    matrix = np.asarray(camera.get('image_to_ground'), dtype=float)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all() or abs(np.linalg.det(matrix)) < 1e-12:
        raise ValueError('image_to_ground ต้องเป็นเมทริกซ์ 3×3 ที่มีค่าจำกัดและผกผันได้')
    return matrix


def calibration_image_size(camera):
    if 'image_size' not in camera:
        return None
    size = np.asarray(camera['image_size'], dtype=float)
    if size.shape != (2,) or not np.isfinite(size).all() or np.any(size < 1) or np.any(size != np.floor(size)):
        raise ValueError('ขนาดภาพ calibration ต้องเป็นจำนวนเต็มบวก [กว้าง, สูง]')
    return size.astype(int).tolist()


def check_image_size(camera, size):
    expected = calibration_image_size(camera)
    if expected is not None and list(size) != expected:
        raise ValueError(f'ขนาดภาพ {size[0]}×{size[1]} ไม่ตรงกับ Camera YAML '
                         f'{expected[0]}×{expected[1]} กรุณาสร้าง calibration ใหม่สำหรับวิดีโอนี้')


def project_points(matrix, points):
    values = np.column_stack((points, np.ones(len(points)))) @ matrix.T
    if not np.isfinite(values).all() or np.any(np.abs(values[:, 2]) < 1e-12):
        raise ValueError('จุดอ้างอิงอยู่บนขอบเขตที่ฉายลงพื้นไม่ได้')
    return values[:, :2] / values[:, 2, None]


def _normalise(points):
    center = points.mean(axis=0)
    shifted = points - center
    spread = np.linalg.svd(shifted, compute_uv=False)
    if spread[0] == 0 or spread[1] < spread[0] * 1e-6:
        raise ValueError('จุดอ้างอิงต้องกระจายเป็นพื้นที่ ไม่อยู่บนเส้นตรงเดียวกัน')
    distances = np.linalg.norm(points[:, None] - points[None, :], axis=2)
    np.fill_diagonal(distances, np.inf)
    if distances.min() < spread[0] * 1e-8:
        raise ValueError('จุดอ้างอิงต้องไม่ซ้ำกัน')
    scale = np.sqrt(2) / np.linalg.norm(shifted, axis=1).mean()
    transform = np.array([[scale, 0, -scale * center[0]],
                          [0, scale, -scale * center[1]], [0, 0, 1]])
    return project_points(transform, points), transform


def rectangle_points(width, length):
    width, length = float(width), float(length)
    if not np.isfinite([width, length]).all() or min(width, length) <= 0:
        raise ValueError('กรอกความกว้างและความยาวจริงเป็นเมตร มากกว่า 0')
    return [[0., 0.], [width, 0.], [width, length], [0., length]]


def calibrate_camera(image_points, ground_points, image_size):
    """Normalised DLT, using every correspondence (no silent point rejection)."""
    pixels, ground = np.asarray(image_points, dtype=float), np.asarray(ground_points, dtype=float)
    if pixels.ndim != 2 or pixels.shape[1:] != (2,) or pixels.shape != ground.shape or len(pixels) < 4:
        raise ValueError('ต้องจับคู่จุดบนภาพกับพิกัดพื้นอย่างน้อย 4 จุด')
    if not np.isfinite(pixels).all() or not np.isfinite(ground).all():
        raise ValueError('พิกัดจุดอ้างอิงต้องเป็นตัวเลขที่มีค่าจำกัด')
    size = np.asarray(image_size, dtype=float)
    if size.shape != (2,) or not np.isfinite(size).all() or np.any(size < 1) or np.any(size != np.floor(size)):
        raise ValueError('ขนาดภาพต้องเป็นจำนวนเต็มบวก [กว้าง, สูง]')
    if np.any(pixels < 0) or np.any(pixels > size - 1):
        raise ValueError('จุดอ้างอิงต้องอยู่ภายในภาพต้นฉบับ')
    source, source_transform = _normalise(pixels)
    destination, destination_transform = _normalise(ground)
    rows = []
    for (u, v), (x, y) in zip(source, destination):
        rows.extend([[-u, -v, -1, 0, 0, 0, x*u, x*v, x],
                     [0, 0, 0, -u, -v, -1, y*u, y*v, y]])
    _, singular, vectors = np.linalg.svd(rows, full_matrices=len(rows) < 9)
    if singular[7] < singular[0] * 1e-8:
        raise ValueError('จุดอ้างอิงไม่เพียงพอสำหรับคำนวณมุมมอง กรุณากระจายจุดใหม่')
    matrix = np.linalg.inv(destination_transform) @ vectors[-1].reshape(3, 3) @ source_transform
    matrix /= np.linalg.norm(matrix)
    if abs(matrix[2, 2]) > 1e-10:
        matrix /= matrix[2, 2]
    camera_matrix(dict(projection='planar_homography', image_to_ground=matrix))
    denominators = np.column_stack((pixels, np.ones(len(pixels)))) @ matrix[2]
    if denominators.min() * denominators.max() <= 0:
        raise ValueError('จุดอ้างอิงคร่อมขอบฟ้า หรือจับคู่พิกัดผิดลำดับ กรุณาตรวจจุดอีกครั้ง')
    errors = np.linalg.norm(project_points(matrix, pixels) - ground, axis=1)
    pixel_errors = np.linalg.norm(project_points(np.linalg.inv(matrix), ground) - pixels, axis=1)
    return dict(projection='planar_homography', image_to_ground=matrix.tolist(),
                image_size=size.astype(int).tolist(), calibration=dict(
                    method='normalised_dlt', units='metres',
                    image_points=pixels.tolist(), ground_points=ground.tolist(),
                    rmse_m=float(np.sqrt(np.mean(errors**2))), max_error_m=float(errors.max()),
                    rmse_px=float(np.sqrt(np.mean(pixel_errors**2)))))
