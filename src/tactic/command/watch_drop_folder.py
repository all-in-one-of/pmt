############################################################
#
#    Copyright (c) 2012, Southpaw Technology
#                        All Rights Reserved
#
#    PROPRIETARY INFORMATION.  This software is proprietary to
#    Southpaw Technology, and is not to be reproduced, transmitted,
#    or disclosed in any way without written permission.
#
#


__all__ = ['WatchDropFolderTask']




import tacticenv
import time, os, shutil, sys
import os.path
import sys

from dateutil import parser
from pyasm.common import Environment, Config, Common
from pyasm.security import Batch
from pyasm.biz import Project
from pyasm.search import DbContainer
from pyasm.search import Search, Transaction, SearchType
from pyasm.command import Command
from tactic.command import SchedulerTask, Scheduler
from time import gmtime, strftime
from optparse import OptionParser

import threading


import logging
logging.basicConfig(filename='/tmp/myapp.log', level=logging.INFO)

from watchdog.observers import Observer
from watchdog.events import LoggingEventHandler


class TestLoggingEventHandler(LoggingEventHandler):
    """Logs all the events captured."""

    def on_moved(self, event):
        super(LoggingEventHandler, self).on_moved(event)

        what = 'directory' if event.is_directory else 'file'
        print "Moved %s: from %s to %s" % (what, event.src_path, event.dest_path)

    def on_created(self, event):
        super(LoggingEventHandler, self).on_created(event)

        what = 'directory' if event.is_directory else 'file'
        print "Created %s: %s" % (what, event.src_path)

    def on_deleted(self, event):
        super(LoggingEventHandler, self).on_deleted(event)

        what = 'directory' if event.is_directory else 'file'
        print "Deleted %s: %s" % (what, event.src_path)

    def on_modified(self, event):
        super(LoggingEventHandler, self).on_modified(event)

        what = 'directory' if event.is_directory else 'file'
        print "Modified %s: %s" % (what, event.src_path)




class WatchFolderFileActionThread(threading.Thread):

    def __init__(my, **kwargs):
        my.kwargs = kwargs
        super(WatchFolderFileActionThread, my).__init__()

    def run(my):

        Batch()
        try:
            my._run()
        finally:
            task = my.kwargs.get("task")
            paths = task.get_paths()
            for path in paths:
                checkin_path = "%s.lock" % path
                if os.path.exists(checkin_path):
                    os.unlink(checkin_path)


    def _run(my):

        task = my.kwargs.get("task")
        paths = task.get_paths()

        count = 0
        restart = False

        while True:
            if not paths:
                time.sleep(1)
                continue

            path = paths.pop(0)

            checkin_path = "%s.checkin" % path
            error_path = "%s.error" % path

            if not os.path.exists(checkin_path):
                print "ERROR: no lock path [%s]" % checkin_path
                continue

            try:

                kwargs = {
                    "project_code": task.project_code,
                    "search_type": task.search_type,
                    "base_dir": task.base_dir,
                    "process": task.process,
                    "path": path
                }


                # create a "custom" command that will act on the file
                cmd = CustomCmd(
                        **kwargs
                )
                cmd.execute()

                # TEST
                #time.sleep(1)
                #if os.path.exists(path):
                #    os.unlink(path)

                count += 1
                if count > 50:
                    restart = True
                    break


            except Exception, e:
                print "Error: ", e
                f = open(error_path,"w")
                f.write(str(e))
                f.close()
                #raise

            finally:
                os.unlink(checkin_path)

        # restart every 20 check-ins
        if restart:
            for path in paths:
                checkin_path = "%s.checkin" % path
                if os.path.exists(checkin_path):
                    os.unlink(checkin_path)
            Common.restart()


class WatchFolderCheckFileThread(threading.Thread):

    def __init__(my, **kwargs):
        my.kwargs = kwargs
        super(WatchFolderCheckFileThread, my).__init__()

        path = my.kwargs.get("path")
        my.lock_path = "%s.lock" % path
        my.error_path = "%s.error" % path
        my.checkin_path = "%s.checkin" % path


    def run(my):

        try:
            path = my.kwargs.get("path")

            if os.path.exists(my.lock_path):
                return

            f = open(my.lock_path, "w")
            f.close()

            changed = my.verify_file_size(path)


            if changed:
                if os.path.exists(my.lock_path):
                    os.unlink(my.lock_path)
                return


            f = open(my.checkin_path, "w")
            f.close()

            task = my.kwargs.get("task")
            task.add_path(path)


        except Exception, e:
            print "Error: ", e
            f = open(my.error_path, "w")
            f.write(str(e))
            f.close()
            raise

        finally:
            if os.path.exists(my.lock_path):
                os.unlink(my.lock_path)


    def verify_file_size(my, file_path):
        '''Check if the file size changes over a period of 5 seconds. If so, file is not ready'''

        # assume nothing has changed
        changed = False

        # Chech whether the file_path exists or not. Once the file is ready, the or
        if not os.path.exists(file_path):
            return True

        for i in range(0, 5):
            file_size = os.path.getsize(file_path)
            mtime = os.path.getmtime(file_path)
            #print "file_size: ", file_size
            #print "mtime: ", mtime

            time.sleep(2)

            if not os.path.exists(file_path):
                changed = True
                break

            file_size2 = os.path.getsize(file_path)
            mtime2 = os.path.getmtime(file_path)
            #print "file_size2: ", file_size2
            #print "mtime2: ", mtime2
            #print

            if file_size != file_size2:
                changed = True
                break
            if mtime != mtime2:
                changed = True
                break

        return changed




class CustomCmd(object):

    def __init__(my, **kwargs):
        my.kwargs = kwargs


    def is_image(my, file_name):
        base, ext = os.path.splitext(file_name)
        ext = ext.lstrip(".").lower()
        if ext in ['tif','tiff','jpg','jpeg','png','pic','bmp','gif','psd']:
            return True
        else:
            return False

    def is_movie(my, file_name):
        base, ext = os.path.splitext(file_name)
        ext = ext.lstrip(".").lower()
        if ext in ['mov','wmv','mpg','mpeg','m1v','mp2','mpa','mpe','mp4','wma','asf','asx','avi','wax','wm','wvx']:
            return True
        else:
            return False

    def get_asset_type(my, file_path):
        if my.is_movie(file_path):
            return 'movie'
        elif my.is_image(file_path):
            return 'image'
        else:
            return 'other'

    def create_checkin_log(my):
        base_dir = my.kwargs.get("base_dir")
        log_path = '%s/TACTIC_log.txt' %(base_dir)
        if not (os.path.isfile(log_path)):
            file = open(log_path, 'w')   
            title='File Name'+40*' '+'Checkin-Time'+20*' '+'Version#'+6*' ' +'Message\n'
            f = open(log_path, 'a')
            f.write(title)
            f.close()




    def execute(my):

        file_path = my.kwargs.get("path")
        project_code = my.kwargs.get("project_code")
        base_dir = my.kwargs.get("base_dir")
        search_type = my.kwargs.get("search_type")
        process = my.kwargs.get("process")
        if not process:
            process = "publish"

        basename = os.path.basename(file_path)

        context = my.kwargs.get("context")
        if not context:
            context = '%s/%s'  % (process, basename)


        # find the relative_dir and relative_path
        relative_path = file_path.replace("%s/" % base_dir, "")
        relative_dir = os.path.dirname(relative_path)

        file_name = os.path.basename(file_path)
        log_path = '%s/TACTIC_log.txt' %(base_dir)
        my.create_checkin_log()

        # Define asset type of the file
        asset_type = my.get_asset_type(file_path)
        description = "drop folder check-in of %s" %file_name

        from client.tactic_client_lib import TacticServerStub
        server = TacticServerStub.get(protocol='local')
        server.set_project(project_code)

        transaction = Transaction.get(create=True)
        server.start(title='Check-in of media', description='Check-in of media')

        server_return_value = {}

        try:
            filters = [
                    [ 'name', '=', file_name ],
                    #[ 'relative_dir', '=', relative_dir ]
                ]
            sobj = server.query(search_type, filters=filters, single=True)

            if not sobj:
                # create sobject if it does not yet exist
                sobj = SearchType.create(search_type)
                if SearchType.column_exists(search_type, "name"):
                    sobj.set_value("name", basename)
                if SearchType.column_exists(search_type, "media_type"):
                    sobj.set_value("media_type", asset_type)


                if SearchType.column_exists(search_type, "relative_dir"):
                    sobj.set_value("relative_dir", relative_dir)

                if SearchType.column_exists(search_type, "keywords"):
                    relative_path = relative_path
                    keywords = Common.get_keywords_from_path(relative_path)
                    keywords = " ".join( keywords )
                    sobj.set_value("keywords", keywords)

                sobj.commit()
                search_key = sobj.get_search_key()
            else:
                search_key = sobj.get("__search_key__")


            #task = server.create_task(sobj.get('__search_key__'),process='publish')
            #server.update(task, {'status': 'New'})

            server_return_value = server.simple_checkin(search_key,  context, file_path, description=description, mode='copy')


            
        except Exception, e:
            print "Error occurred", e
            error_message=str(e)
            version_num='Error:'
            system_time=strftime("%Y/%m/%d %H:%M", gmtime())
            pre_log=file_name+(50-len(file_name))*' '+system_time+(33-len(system_time))*' '+version_num+(15-len(version_num))*' ' +error_message+'\n'      
            # Write data into TACTIC_log file under /tmp/drop
            f = open(log_path, 'a')
            f.write(pre_log)
            f.close()

            #server.abort()
            transaction.rollback()
            raise
        
        else:
            transaction.commit()
        
        #server.finish()

        if server_return_value:
            # Create the TACTIC_log file to record every check-in. 
            # Search for all required data
            checkin_time=server_return_value.get('timestamp')
            version_nu=server_return_value.get('version')
            version_num=str(version_nu)
            try:
                value = parser.parse(checkin_time)
                value = value.strftime("%Y/%m/%d %H:%M")
            except:
                value = checkin_time

            pre_log=file_name+(50-len(file_name))*' '+value+(33-len(value))*' '+version_num+(15-len(version_num))*' ' +'ok\n'      
            # Write data into TACTIC_log file under /tmp/drop
            f = open(log_path, 'a')
            f.write(pre_log)
            f.close()

            # Delete the sourse file after check-in step.
            print "File checked in. Source file [%s] deleted: " %file_name
            os.unlink(file_path)







class WatchDropFolderTask(SchedulerTask):

    def __init__(my, **kwargs):

        my.base_dir = kwargs.get("base_dir")
        my.project_code = kwargs.get("project_code")
        my.search_type = kwargs.get("search_type")
        my.process = kwargs.get("process")

        super(WatchDropFolderTask, my).__init__()

        my.checkin_paths = []


    def add_path(my, path):
        my.checkin_paths.append(path)

    def get_paths(my):
        return my.checkin_paths




    def _execute(my):

        base_dir = my.base_dir
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)

        dirs = os.listdir(base_dir)
        test_dirs = dirs[:]
        for dirname in test_dirs:
            base, ext = os.path.splitext(dirname)
            if ext in [".lock", ".error", ".checkin"]:
                dirs.remove(dirname)

                try:
                    dirs.remove(base)
                except:
                    pass

        if not dirs:
            return

        # skip certain files like log
        dir_set = set(dirs)
        for dirname in dirs:
            if dirname.startswith("TACTIC_log"):
                dir_set.remove(dirname)
            if dirname.startswith("."):
                dir_set.remove(dirname)
        dirs = list(dir_set)

        if not dirs:
            return

        #print "Found new: ", dirs

        # go thru the list to check each file
        for file_name in dirs:

            file_path = '%s/%s' %(my.base_dir, file_name)
            thread = WatchFolderCheckFileThread(
                    task=my,
                    path=file_path
                    )
            thread.daemon = True
            thread.start()



    def execute(my):

        base_dir = my.base_dir
        if not base_dir:
            print "WARNING: No base dir defined."
            return


        # Start check-in thread
        checkin = WatchFolderFileActionThread(
                task=my,
                )
        checkin.start()

        # execute and react based on a loop every second
        mode = "loop"
        if mode == "loop":
            while True:
                my._execute()
                time.sleep(1)


        elif mode == "event":

            try:
                event_handler = TestLoggingEventHandler()
                observer = Observer()

                print "base: ", my.base_dir
                path = my.base_dir
                observer.schedule(event_handler, path=path, recursive=True)
                observer.start()

            except Exception, e:
                print "... skipping: ", e
                raise

            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                for observer in observers:
                    observer.stop()






    def start(cls):

        print "Running Watch Folder ..."

        # Check whether the user define the drop folder path.
        # Default dop folder path: /tmp/drop
        parser = OptionParser()
        parser.add_option("-p", "--project", dest="project", help="Define the project_name.")
        parser.add_option("-d", "--drop_path", dest="drop_path", help="Define drop folder path")
        parser.add_option("-s", "--search_type", dest="search_type", help="Define search_type.")
        parser.add_option("-P", "--process", dest="process", help="Define process.")
        (options, args) = parser.parse_args()

        if options.project != None :
            project_code= options.project
        else:
            project_code= 'jobs'

        if options.drop_path!=None :
            drop_path= options.drop_path
        else:
            tmp_dir = Environment.get_tmp_dir()
            drop_path = "%s/drop" % tmp_dir
        print "    using [%s]" % drop_path
        if not os.path.exists(drop_path):
            os.makedirs(drop_path)

        if options.search_type!=None :
            search_type = options.search_type
        else:
            search_type = 'jobs/media'

        if options.process!=None :
            process = options.process
        else:
            process= 'publish'


        task = WatchDropFolderTask(base_dir=drop_path, project_code=project_code,search_type=search_type, process=process)
        
        scheduler = Scheduler.get()
        scheduler.add_single_task(task, delay=1)
        scheduler.start_thread()
        return scheduler
    start = classmethod(start)

if __name__ == '__main__':
    Batch()
    WatchDropFolderTask.start()
    while 1:
        try:
            time.sleep(15)
        except (KeyboardInterrupt, SystemExit), e:
            scheduler = Scheduler.get()
            scheduler.stop()
            break



