from pathlib import Path

path = Path(__file__).parent.resolve()
import unittest
from etcher.db import DB, DBConnections, WatchError, list_db
from ulid import ULID

import shutil, tempfile
from pprint import pprint
import time

class Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp()
        name = 'test_' + str(ULID()) + '.db'
        cls.dbfname = str(cls.test_dir + '/' + name)
        cls.db = DB(cls.dbfname, 'db', link_field='id')


    def setUp(self):
        # Set up temp db for each test.
        pass
        # name = 'test_' + str(ULID()) + '.db'
        # self.dbfname = str(self.test_dir + '/' + name)
        # self.db = DB(self.dbfname, 'db', link_field='id')

    def tearDown(self):
        prefix = self.db.get_prefix()
        self.db.delete_prefix_immediately(prefix)
        

    @classmethod
    def tearDownClass(cls):
        #time.sleep(0.2)
        cls.db.shutdown()
        shutil.rmtree(cls.test_dir)

    def test_set(self):
        keys = [x.decode('utf8') for x in self.db.rdb.keys()]
        assert keys == ['back:db:data:']
        assert self.db.backrefs == {':root:': 1}
        assert ':root:' in self.db.backrefs
        self.db['x'] = {'a':2}
        assert self.db['x'].backrefs == {'db:data:': 1}
        assert 'db:data:' in self.db['x'].backrefs
        keys = [x.decode('utf8') for x in self.db.rdb.keys()]
        assert len(keys) == 4
        xuid = self.db['x'].uid
        self.db['x']['y'] = {1:2}
        keys = [x.decode('utf8') for x in self.db.rdb.keys()]
        assert len(keys) == 6   
        assert xuid in self.db['x']['y'].backrefs
        assert self.db['x']['y'].backrefs[xuid] == 1
        self.db['x']['z'] = self.db['x']['y']
        assert self.db['x']['y'].backrefs[xuid] == 2
        del self.db['x']['z']
        assert self.db['x']['y'].backrefs[xuid] == 1


    def test_consume_list(self):
        self.db['x'] = [{1:2}, {2:3}, {3:4}]
        assert self.db['x'].refcount == 1
        assert self.db['x'][0].refcount == 1
        
        y = [{1:2}, {2:3}, {3:4}]
        assert self.db['x'][0] == {1:2}
        assert self.db['x'][1:] == y[1:]
        
        x = self.db['x'][0]
        z = self.db['x'][1]
        self.db['x'] = self.db['x'][1:]
        
        y = y[1:]
        assert self.db['x'][0] == {2:3}
        assert self.db['x'][1:] == y[1:]      
        self.db['x'] =  [a() for a in self.db['x'][1:]]
        y = y[1:]
        assert self.db['x'][0] == {3:4}
        assert self.db['x'][1:] == y[1:]
        self.db['x'] =  [a() for a in self.db['x'][1:]]
        y = y[1:]
        assert self.db['x'] == []
        assert y == []


    def test_basic_dict(self):
        self.db['x'] = {'name': 'bob'}
        assert self.db['x']() == {'name': 'bob'}
        assert str(self.db['x']) == "@{'name': 'bob'}"
        keys = [x.decode('utf8') for x in self.db.rdb.keys()]
        assert len(keys) == 4
        assert 'x' in self.db
        found_rc = False
        found_k = False
        for k in keys:
            if k.startswith('back:db:D'):
                found_rc = True
            if k.startswith('db:D'):
                found_k = True
        assert found_k
        assert found_rc

    def test_encoded_dict(self):
        self.db['x'] = {'name': None, 'x': True, 'y': False}
        assert self.db['x']() == {'name': None, 'x': True, 'y': False}
        assert str(self.db['x']) == "@{'name': None, 'x': True, 'y': False}"
        keys = [x.decode('utf8') for x in self.db.rdb.keys()]
        assert len(keys) == 4
        assert 'x' in self.db
        found_rc = False
        found_k = False
        for k in keys:
            if k.startswith('back:db:D'):
                found_rc = True
            if k.startswith('db:D'):
                found_k = True
        assert found_k
        assert found_rc

    def test_basic_list(self):
        self.db['x'] = [1, 2, 3]
        assert self.db['x']() == [1, 2, 3]
        assert str(self.db['x']) == "@[1, 2, 3]"
        keys = [x.decode('utf8') for x in self.db.rdb.keys()]
        assert len(keys) == 4
        assert 'x' in self.db
        found_rc = False
        found_k = False
        for k in keys:
            if k.startswith('back:db:L'):
                found_rc = True
            if k.startswith('db:L'):
                found_k = True
        assert found_k
        assert found_rc

    
    def test_basic_dereference(self):
        keys = [x.decode('utf8') for x in self.db.rdb.keys()]
        assert len(keys) == 1
        self.db['x'] = {'name': 'bob'}
        keys = [x.decode('utf8') for x in self.db.rdb.keys()]
        assert len(keys) == 4
        # overwrite
        self.db['x'] = [1, 2, 3]
        assert self.db['x']() == [1, 2, 3]
        assert str(self.db['x']) == "@[1, 2, 3]"
        keys = [x.decode('utf8') for x in self.db.rdb.keys()]
        assert len(keys) == 4
        assert 'x' in self.db
        found_lrc = False
        found_lk = False
        found_drc = False
        found_dk = False
        for k in keys:
            if k.startswith('back:db:L'):
                found_lrc = True
            if k.startswith('db:L'):
                found_lk = True
            if k.startswith('back:db:D'):
                found_drc = True
            if k.startswith('db:D'):
                found_dk = True
        assert found_lk
        assert found_lrc
        assert not found_dk
        assert not found_drc


    def test_complicated_dereference(self):
        assert len(self.db.rdb.keys()) == 1
        self.db['x'] = {'name': 'bob'}
        assert len(self.db.rdb.keys()) == 4
        x = self.db['x']

        self.db['y'] = [1, 2, x, x]

        assert self.db['x'].refcount == 2
        assert self.db['y'].refcount == 1
        assert len(self.db.rdb.keys()) == 6
        assert self.db['x']() == {'name': 'bob'}
        assert self.db['y']() == [1, 2, {'name': 'bob'}, {'name': 'bob'}]
        assert len(self.db.rdb.keys()) == 6
        assert self.db['x'].refcount == 2
        assert self.db['y'].refcount == 1

        x['name'] = 'alice'
        assert self.db['x']() == {'name': 'alice'}
        assert self.db['y']() == [1, 2, {'name': 'alice'}, {'name': 'alice'}]
        assert len(self.db.rdb.keys()) == 6

        del self.db['x']
        assert 'x' not in self.db
        assert self.db['y'][2].refcount == 1

        assert len(self.db.rdb.keys()) == 6
        assert self.db['y']() == [1, 2, {'name': 'alice'}, {'name': 'alice'}]

        z = self.db['y']()[:2]
        self.db['y'] = z
        assert len(self.db.rdb.keys()) == 4
        assert self.db['y']() == [1, 2]

        del self.db['y']
        assert 'y' not in self.db
        assert len(self.db.rdb.keys()) == 1

    def test_multiple_reference(self):
        assert len(self.db.rdb.keys()) == 1
        self.db['x'] = {'name': 'bob'}
        assert len(self.db.rdb.keys()) == 4
        x = self.db['x']
        self.db['y'] = [x, x]
        assert self.db['x'].refcount == 2
        assert self.db['y'].refcount == 1
        assert len(self.db.rdb.keys()) == 6
        self.db['y'][1] = 1
        del self.db['x']
        assert self.db['y'][0] == x 
        assert self.db['y'][0]() == {'name': 'bob'}
        assert self.db['y'][0].refcount == 1
        assert self.db['y'].refcount == 1
        assert len(self.db.rdb.keys()) == 6
        self.db['y'][0] = 1
        assert len(self.db.rdb.keys()) == 4
        del self.db['y']
        assert 'y' not in self.db
        assert len(self.db.rdb.keys()) == 1


    def test_list_slice(self):
        self.db['x'] = [1, 2, 3, 4]
        y = [1, 2, 3, 4]
        assert self.db['x'][:2] == y[:2]
        assert self.db['x'][:-1] == y[:-1]
        assert self.db['x'][0:] == y[0:]
        assert self.db['x'][1:3] == y[1:3]
        assert self.db['x'][-2:] == y[-2:]
        self.db['x'] = self.db['x'][-2:]
        assert self.db['x']() == y[-2:]


    def test_transaction(self):
        self.db['x'] = [1, 2, 3, 4]
        t = self.db.transactor()
        t.watch()
        t.multi()
        t['x'] = [1, 2, 3, 4, 5, 6]
        t.execute()
        assert self.db['x']() == [1, 2, 3, 4, 5, 6]

    def test_transaction_blocks(self):
        self.db['x'] = [1, 2, 3, 4]
        t1 = self.db.transactor()
        t1.watch()
        t1.multi()
        t1['x'] = [1, 2, 3, 4, 5, 6]

        t2 = self.db.transactor()
        t2.watch()
        t2.multi()
        t2['x'] = [1, 2, 3, 4, 5, 6]
        t2.execute()
        with self.assertRaises(WatchError):
            t1.execute()

    def test_transact(self):
        self.db['x'] = [1, 2, 3, 4]
        t = self.db.transactor()

        # Autoretry
        def tfunc():
            y = t['x']()
            y = y + [5, 6]
            t.multi()
            t['x'] = y

        t.transact(tfunc)
        assert self.db['x']() == [1, 2, 3, 4, 5, 6]


    def test_circular_reference(self):
        # Create a circular reference
        assert len(self.db.rdb.keys()) == 1
        x = self.db()
        assert x == {}

        self.db['a'] = {'name': 'object A'}
        assert self.db['a'].refcount == 1
        self.db['b'] = {'name': 'object B', 'ref_to_a': self.db['a']}
        assert self.db['b'].refcount == 1
        assert self.db['a'].refcount == 2
        self.db['a']['ref_to_b'] = self.db['b']
        assert self.db['a'].refcount == 2
        assert self.db['b'].refcount == 2
        
        x = self.db()
        #pprint(list_db(self.db))
        
        # The keys in the database should increase to account for 'a' and 'b' and their reference counts
        assert len(self.db.rdb.keys()) == 6  # Adjust this based on your implementation

        # Delete one of the circular references
        del self.db['a']
        assert self.db['b']['ref_to_a'].refcount == 1
        
        # 'a' should no longer be directly accessible, but its data should persist due to the reference from 'b'
        assert 'a' not in self.db
        #print(self.db['b']())
        assert self.db['b']['ref_to_a']['name'] == 'object A'

        # Delete the other reference
        del self.db['b']
        # Now both 'a' and 'b' should be completely dereferenced
        assert 'b' not in self.db

        x = self.db()
        assert x == {}

        assert len(self.db.rdb.keys()) == 1 

    def test_shared_nested_objects_with_non_simultaneous_deletion(self):
        # Create a shared nested object
        assert len(self.db.rdb.keys()) == 1
        self.db['C'] = {'shared_key': 'shared_value'}
        nested_dict = self.db['C']
        self.db['A'] = {'nested': nested_dict}
        self.db['B'] = {'nested': nested_dict}
        # Verify both A and B have the shared nested object
        self.assertEqual(self.db['A']()['nested'], nested_dict)
        self.assertEqual(self.db['B']()['nested'], nested_dict)
        assert len(self.db.rdb.keys()) == 8
        # Delete A and check if the nested object is still accessible through B
        del self.db['A']
        self.assertNotIn('A', self.db)
        self.assertIn('B', self.db)
        self.assertEqual(self.db['B']()['nested'], nested_dict)
        assert len(self.db.rdb.keys()) == 6
        # Delete B and verify that the nested object is also dereferenced
        del self.db['B']
        self.assertNotIn('B', self.db)
        assert len(self.db.rdb.keys()) == 4
        del self.db['C']
        self.assertNotIn('C', self.db)
        assert len(self.db.rdb.keys()) == 1

    def test_dict_deletion(self):
        # Create a shared nested object
        locale = {'shared_key': 'shared_value'}
        self.db['C'] = locale
        
        nested_dict = self.db['C']
        self.db['A'] = {'nested': nested_dict}
        self.db['B'] = self.db['C']
        self.db['B'] = self.db['A']
        self.db['D'] = {}
        del self.db['A']['nested']

        assert self.db['A'] == {}
        assert self.db['A'].values() == []

        assert self.db['B'] == self.db['A']
        assert self.db['C']

    def test_reassignment_and_reference_counting(self):
        # Initial setup: Create a dictionary and a list, both of which will be reused.
        initial_dict = {'key': 'value'}
        initial_list = [1, 2, 3]

        # Step 1: Assign initial structures to keys
        self.db['dict1'] = initial_dict
        self.db['list1'] = initial_list

        # Step 2: Reassign to the same values (no actual change in reference)
        self.db['dict1'] = initial_dict
        self.db['list1'] = initial_list

        # Step 3: Direct reassignment to new structures
        self.db['dict1'] = {'new_key': 'new_value'}
        self.db['list1'] = [4, 5, 6]

        # Verify the reassignments took effect
        assert self.db['dict1']() == {'new_key': 'new_value'}
        assert self.db['list1']() == [4, 5, 6]

        # Step 4: Reassignment involving shared references
        self.db['shared'] = {'shared_key': 'shared_value'}
        shared_ref = self.db['shared']

        self.db['container1'] = {'ref': shared_ref}
        self.db['container2'] = {'ref': shared_ref}

        # Directly modify 'shared' and ensure the changes propagate
        self.db['shared']['shared_key'] = 'modified_value'
        assert self.db['container1']['ref']['shared_key'] == 'modified_value'
        assert self.db['container2']['ref']['shared_key'] == 'modified_value'

        # Step 5: Remove one container and check if shared_ref is still accessible
        del self.db['container1']
        assert self.db['container2']['ref']['shared_key'] == 'modified_value'

        # Step 6: Overwrite the shared reference with a new value and check reference counts
        self.db['shared'] = 'completely_new_value'
        assert self.db['shared'] == 'completely_new_value'

        # Step 7: Cleanup and final assertions
        del self.db['container2']
        del self.db['shared']
        assert 'container1' not in self.db
        assert 'container2' not in self.db
        assert 'shared' not in self.db

        # Final checks on the reference counts (pseudo-code, implement based on your system's internals)
        # # Verify no negative reference counts exist
        # for key in self.db.internal_keys():
        #     ref_count = self.db.get_reference_count(key)
        #     assert ref_count >= 0, f"Negative reference count found for key: {key}"

    def test_complex_reassignments_with_cycles(self):
        # Step 1: Create objects with cyclic references
        self.db['objA'] = {'name': 'A'}
        self.db['objB'] = {'name': 'B', 'refA': self.db['objA']}
        self.db['objA']['refB'] = self.db['objB']  # Create cyclic reference
        
        # Verify the cyclic references work as expected
        assert self.db['objA']['refB']['name'] == 'B'
        assert self.db['objB']['refA']['name'] == 'A'

        # Step 2: Reassign one of the objects in the cycle to break it and replace it with new data
        self.db['objA'] = {'newData': 'newValue'}

        # Verify that the new assignment worked and the old reference is broken
        assert self.db['objA']() == {'newData': 'newValue'}
        assert 'refB' not in self.db['objA']
    
        # Step 3: Introduce another set of objects with references and perform reassignments
        self.db['objC'] = [self.db['objA'], self.db['objB']]
        self.db['objD'] = {'partOfC': self.db['objC']}

        # Perform a series of reassignments
        self.db['objC'] = self.db['objC'] + [{'extra': 'data'}]
        self.db['objD']['newPart'] = {'completely': 'new'}

        # Verify updates
        assert len(self.db['objC']) == 3  # Original 2 + 1 new
        assert self.db['objD']['newPart']['completely'] == 'new'

        # Step 4: Remove references and perform cleanup, focusing on cyclic and complex structures
        del self.db['objB']['refA']  # Break the original cycle explicitly
        del self.db['objD']  # Delete an object with nested references

        # Final checks: Ensure cleanup is effective and reference counts are sane
        assert 'objD' not in self.db
        assert self.db['objC']()[0]['newData'] == 'newValue'  # objA through objC

        # Additional checks for lingering references or unexpected data
        assert 'objB' in self.db and 'refA' not in self.db['objB'](), "objB incorrectly retains refA"

    def test_object_reassignments(self):
        from ulid import ULID
        import time 

        def genid(name=''):
            return name+':'+str(ULID())
        
        class AttrDict(dict):
            def __init__(self, *args, **kwargs):
                super(AttrDict, self).__init__(*args, **kwargs)
                self.__dict__ = self

        class Action(AttrDict):
            pass 
    
        self.db['person'] = {'action-queue':{}, 'action': None, 'id': str(ULID()) }
        person = self.db['person']

        def create_action():
            action = Action(id=genid('action'), some='data',code={'cmd':'some','kwargs':{'c':2,'a':'b'}},duration=3,when=time.perf_counter())
            return action

        def add_action(person,action):
            person['action-queue'][action['id']] = action.__dict__
            assert person['action-queue'][action['id']].refcount == 1
            if person['action'] is None:
                person['action'] = person['action-queue'][action['id']]
                assert person['action-queue'][action['id']].refcount == 2
                assert person['action'].refcount == 2
                assert person['action']['code'].refcount == 1

        
        def pop_action(person):
            action = person['action']
            assert person['action'].refcount == 2
            assert person['action']['code'].refcount == 1
            if action:
                del person['action-queue'][action['id']] 
                assert person['action'].refcount == 1
                assert person['action']['code'].refcount == 1
                if person['action-queue']:
                    # Get first one sorted by ULID
                    aid = sorted(person['action-queue'].keys())[0]
                    assert person['action-queue'][aid].refcount == 1
                    assert person['action'].refcount == 1
                    person['action'] = person['action-queue'][aid]                   
                    person['action']['when'] = time.perf_counter()
                else:
                    person['action'] = None
        
        add_action(person,create_action())
        add_action(person,create_action())
        add_action(person,create_action())
        pop_action(person)
        pop_action(person)

    def test_nested_object_reassignments(self):
        from ulid import ULID
        import time 

        def genid(name=''):
            return name+':'+str(ULID())
        
        class AttrDict(dict):
            def __init__(self, *args, **kwargs):
                super(AttrDict, self).__init__(*args, **kwargs)
                self.__dict__ = self

        class Action(AttrDict):
            pass 
    
        self.db['person'] = {'action-queue':{}, 'action': None, 'id': str(ULID()) }
        person = self.db['person']

        def create_action():
            action = Action(id=genid('action'), some='data',code={'cmd':'some','kwargs':{'c':2,'a':'b'}},duration=3,when=time.perf_counter())
            return action

        def add_action(person,action):
            person['action-queue'][action['id']] = action.__dict__
            assert person['action-queue'][action['id']].refcount == 1
            if person['action'] is None:
                person['action'] = person['action-queue'][action['id']]
                assert person['action-queue'][action['id']].refcount == 2
                assert person['action'].refcount == 2
                assert person['action']['code'].refcount == 1
            return action['id']

        def modify_action(person,action_id):
            action = person['action-queue'][action_id] 
            assert person['action-queue'][action_id].refcount == 2
            assert person['action-queue'][action_id]['code'].refcount == 1
            assert person['action-queue'][action_id]['code']['kwargs'].refcount == 1
            #oldref_code = person['action-queue'][action_id]['code'].ref
            #oldref_kwargs = person['action-queue'][action_id]['code'].ref
            #assert int(self.db.pipe.get(oldref_code)) == 1
            #assert int(self.db.pipe.get(oldref_kwargs)) == 1
            # This is the problem.  Reassignment has to inherit the old ref count.
            action['code'] = {'some': 'new data', 'kwargs': {'others':1}}
            #assert person['action-queue'][action_id]['code'].ref != oldref_code
            assert person['action-queue'][action_id]['code'].refcount == 1
            assert person['action-queue'][action_id]['code']['kwargs'].refcount == 1
            
            #assert self.db.pipe.get(oldref_code) is None
            #assert self.db.pipe.get(oldref_kwargs) is None

        
        def pop_action(person):
            action = person['action']
            assert person['action'].refcount == 2
            assert person['action']['code'].refcount == 1
            if action:
                del person['action-queue'][action['id']] 
                assert person['action'].refcount == 1
                assert person['action']['code'].refcount == 1
                if person['action-queue']:
                    # Get first one sorted by ULID
                    aid = sorted(person['action-queue'].keys())[0]
                    assert person['action-queue'][aid].refcount == 1
                    assert person['action'].refcount == 1
                    person['action'] = person['action-queue'][aid]                   
                    person['action']['when'] = time.perf_counter()
                    assert person['action-queue'][aid].refcount == 2
                    assert person['action'].refcount == 2
                else:
                    assert person['action'].refcount == 1
                    assert person['action']['code'].refcount == 1
                    #oldref = action.ref
                    person['action'] = None
                    #assert self.db.pipe.get(oldref) is None
                    
        action_id = add_action(person,create_action())
        modify_action(person,action_id)
        pop_action(person)
       
