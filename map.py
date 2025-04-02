import folium
import openrouteservice

# ใส่ API Key ของคุณที่ได้จาก OpenRouteService
client = openrouteservice.Client(key='5b3ce3597851110001cf6248d13d2b628357479288dcac285dd42fe5')

# พิกัดเริ่มต้นและปลายทาง
start = [8.34234, 48.23424]
end = [8.34423, 48.26424]

# คำนวณเส้นทาง
route = client.directions(
    coordinates=[start, end],
    profile='driving-car',  # ประเภทการเดินทาง เช่น 'driving-car', 'cycling-regular', 'foot-walking'
    format='geojson'
)

# สร้างแผนที่ในตำแหน่งเริ่มต้น
m = folium.Map(location=start, zoom_start=14)

# เพิ่มเส้นทางบนแผนที่
route_coordinates = route['features'][0]['geometry']['coordinates']
folium.PolyLine(route_coordinates, color='blue', weight=5, opacity=0.7).add_to(m)

# เพิ่มจุดเริ่มต้นและปลายทาง
folium.Marker(location=start, popup='Start', icon=folium.Icon(color='green')).add_to(m)
folium.Marker(location=end, popup='End', icon=folium.Icon(color='red')).add_to(m)

# แสดงแผนที่
m.save('route_map.html')

# ข้อความแจ้งเตือน
print("แผนที่ได้ถูกบันทึกเป็น route_map.html สามารถเปิดได้ในเว็บเบราว์เซอร์")
