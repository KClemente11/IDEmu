"""GPS must reach both native CDS (instance 1) and navigation UI (instance 3)."""
import struct
import unittest
from idemu import most

class Gps:
    values=dict(fix=True,lat=41.881832,lon=-87.623177,alt=180.0,heading=90.0,speed_kmh=30.0,sats=9,hdop=0.9)
    def state(self):return dict(self.values)

class Bridge:
    def __init__(self):
        self.subs={(0xCD,1):{0x202:0x2000,0x203:0x2000},(0xCD,3):{0x202:0x2000,0x203:0x2000}}
        self.sent=[]
    def publish(self,fb,fkt,data,inst):self.sent.append((fb,inst,fkt,data));return 1

class CdsGpsTests(unittest.TestCase):
    def setUp(self):
        self.bridge=Bridge();self.car=most.MostCar(self.bridge);self.car.gps=Gps()
        self.car.gps.values=dict(Gps.values)
    def test_same_position_and_heading_on_both_instances(self):
        for fkt in (0x202,0x203):
            self.assertEqual(self.car.status_for(0xCD,1,fkt),self.car.status_for(0xCD,3,fkt))
        self.assertEqual(self.car.status_for(0xCD,1,0x203)[0],64)
        self.assertEqual(struct.unpack('>II',self.car.status_for(0xCD,1,0x202)),
                         (0x80000000+round(-87.623177*3600000),0x80000000+round(41.881832*3600000)))
    def test_live_changes_publish_to_each_subscriber(self):
        self.assertEqual(self.car.publish_all(),4)
        self.assertEqual(self.car.publish_all(),0)
        self.car.gps.values.update(lat=41.882,heading=180)
        self.assertEqual(self.car.publish_all(),4)
        self.assertEqual({(fb,inst,fkt) for fb,inst,fkt,_ in self.bridge.sent[-4:]},
                         {(0xCD,inst,fkt) for inst in (1,3) for fkt in (0x202,0x203)})
    def test_no_fix_preserves_invalid_coordinates(self):
        self.car.gps.values['fix']=False
        for inst in (1,3):self.assertEqual(self.car.status_for(0xCD,inst,0x202),b'\xff'*8)
    def test_other_instances_are_not_fabricated(self):
        self.assertIsNone(self.car.status_for(0xCD,2,0x202))

if __name__=='__main__':unittest.main()
