#!/usr/bin/env python

import MySQLdb
import sys

def sql_updater(command,values):
        sql_file = sys.argv[1]
        #Define SQL connection parameters
        open_sql_file = open(sql_file, 'r')
        open_sql_file.seek(0)
        sql_host = open_sql_file.readlines()[0].split(',')[0]
        open_sql_file.seek(0)
        sql_username = open_sql_file.readlines()[0].split(',')[1]
        open_sql_file.seek(0)
        sql_password = open_sql_file.readlines()[0].split(',')[2]
        open_sql_file.seek(0)
        sql_database = open_sql_file.readlines()[0].split(',')[3].rstrip("\n")

        #Connecting and writing to database
        try:
                sql_conn = MySQLdb.connect(sql_host, sql_username, sql_password, sql_database)
                cursor = sql_conn.cursor()
                cursor.execute("USE MunHug")
                cursor.execute(command,values)
                #Commit changes
                sql_conn.commit()

        except MySQLdb.Error, e:
                #Print any SQL errors to the error log file
                print "MySQL Error or duplicated IP. Fix it and try again"

        #Closing the sql file
        open_sql_file.close()

def add_host():
	host_ip = sys.argv[2]
	sql_updater("INSERT INTO Hosts (MgmtAddress) VALUES(%s)",(host_ip,))

add_host()
