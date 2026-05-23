#####################################################
# DVrouter.py
# Name:
# HUID:
#####################################################

import json
from router import Router
from packet import Packet

INF = 999  # Dùng để đánh dấu route không thể đi được

class DVrouter(Router):
    def __init__(self, addr, heartbeat_time):
        Router.__init__(self, addr)  
        self.heartbeat_time = heartbeat_time  
        self.last_time = 0                    

        self.neighbors = {} # port : (đ/c neighbor, cost)
        self.distance_vector = {addr: 0}  # chi phí tốt nhất, đích : cost (tự nó = 0)
        self.forwarding_table = {}  # Bảng chuyển tiếp, đích : port cần gửi ra
        self.neighbor_vectors = {}  # DV nhận từ neighbor, đ/c neighbor : {đích : cost}

    def send_dv(self):
        """Gửi distance vector của mình cho tất cả neighbor, áp dụng poison reverse."""
        for port, (neighbor_addr, _) in self.neighbors.items():
            poisoned_dv = {}
            for dest, cost in self.distance_vector.items():
                # Poison reverse: nếu route tới đích này đang đi qua neighbor đó thì báo cost = INF 
                if dest in self.forwarding_table and self.forwarding_table[dest] == port:
                    poisoned_dv[dest] = INF
                else:
                    poisoned_dv[dest] = cost

            # Đóng gói thành routing packet và gửi đi
            pkt = Packet(
                Packet.ROUTING,
                self.addr,
                neighbor_addr,
                json.dumps(poisoned_dv)
            )
            self.send(port, pkt)

    def update_routing(self):
        """
        Dùng Bellman-Ford tính lại distance vector và forwarding table.
        Trả về True nếu có thay đổi.
        """
        new_distance_vector = {self.addr: 0}  
        new_forwarding_table = {}

        # Gom tất cả các đích: DV của các neighbor & neighbor trực tiếp
        all_destinations = set()
        for neighbor_dv in self.neighbor_vectors.values():
            all_destinations.update(neighbor_dv.keys())
        for _, (neighbor_addr, _) in self.neighbors.items():
            all_destinations.add(neighbor_addr)
        all_destinations.discard(self.addr)  

        # Với mỗi đích, tìm neighbor cho cost thấp nhất 
        for dst in all_destinations:
            best_cost = INF       
            best_out_port = None  

            for port, (neighbor_addr, cost_to_neighbor) in self.neighbors.items():
                # Nếu đích là neighbor thì cost = cost của link trực tiếp
                if dst == neighbor_addr:
                    if cost_to_neighbor < best_cost:
                        best_cost = cost_to_neighbor
                        best_out_port = port
                    continue

                # Nếu đích phải đi qua neighbor này 
                # -> tra DV của neighbor để biết cost từ neighbor tới đích
                if neighbor_addr not in self.neighbor_vectors:
                    continue  # Chưa nhận DV từ neighbor này, bỏ qua
                neighbor_dv = self.neighbor_vectors[neighbor_addr]
                if dst not in neighbor_dv:
                    continue  # Neighbor không biết đường tới đích này, bỏ qua

                # Bỏ qua nếu neighbor báo cost = INF 
                if neighbor_dv[dst] >= INF:
                    continue

                # Tổng cost = cost tới neighbor + cost từ neighbor tới đích
                total_cost = cost_to_neighbor + neighbor_dv[dst]
                if total_cost < best_cost:
                    best_cost = total_cost
                    best_out_port = port

            # Chỉ lưu nếu tìm được route hợp lệ
            if best_out_port is not None and best_cost < INF:
                new_distance_vector[dst] = best_cost
                new_forwarding_table[dst] = best_out_port

        # Kiểm tra có thay đổi không để quyết định có gửi DV mới không
        changed = (new_distance_vector != self.distance_vector or
                   new_forwarding_table != self.forwarding_table)
        self.distance_vector = new_distance_vector
        self.forwarding_table = new_forwarding_table
        return changed

    def handle_packet(self, port, packet):
        """Xử lý packet đến từ một port."""
        if packet.is_traceroute:
            # Packet dữ liệu thông thường -> tra forwarding table rồi chuyển tiếp
            dst = packet.dst_addr
            if dst in self.forwarding_table:
                self.send(self.forwarding_table[dst], packet)
        else:
            # Packet định tuyến -> đây là DV mà neighbor gửi cho mình
            neighbor_addr = packet.src_addr
            try:
                received_dv = json.loads(packet.content)  # chuyển JSON thành dict, pk lỗi -> bỏ qua
            except Exception:
                return 

            # Chỉ tính toán lại nếu DV của neighbor thực sự thay đổi
            if self.neighbor_vectors.get(neighbor_addr) != received_dv:
                self.neighbor_vectors[neighbor_addr] = received_dv
                if self.update_routing():
                    self.send_dv()  # Có thay đổi -> báo cho các neighbor khác

    def handle_new_link(self, port, endpoint, cost):
        """Xử lý khi có link mới được thêm vào."""
        self.neighbors[port] = (endpoint, cost)
        # Khởi tạo DV mặc định cho neighbor mới nếu chưa có
        if endpoint not in self.neighbor_vectors:
            self.neighbor_vectors[endpoint] = {endpoint: 0}
        self.update_routing() # Tính lại route
        self.send_dv() # Thông báo cho các neighbor còn lại

    def handle_remove_link(self, port):
        """Xử lý khi một link bị xóa."""
        if port not in self.neighbors:
            return
        neighbor_addr, _ = self.neighbors.pop(port)  # Xóa khỏi danh sách neighbor
        self.neighbor_vectors.pop(neighbor_addr, None)  # Xóa DV của neighbor đó
        self.update_routing() 
        self.send_dv()         

    def handle_time(self, time_ms):
        """Gửi DV định kỳ để neighbor biết mình vẫn còn sống."""
        if time_ms - self.last_time >= self.heartbeat_time:
            self.last_time = time_ms
            self.send_dv()

    def __repr__(self):
        """Hiển thị thông tin router khi debug trong network visualizer."""
        return f"DVrouter(addr={self.addr}, dv={self.distance_vector}, nh={self.forwarding_table})"