# by Greg Hughes <greg@ghughes.com>
# based on insidebot

## From twisted
from twisted.internet.protocol import Protocol, ClientFactory
from twisted.internet import reactor, task
## built in
from gzip import GzipFile
from StringIO import StringIO
import struct, socket, time, math, array, re, sys, os
## other libraries
import mechanize
sys.path.append(os.path.abspath(os.path.dirname(sys.executable)))
print sys.path
from config import *
from PIL import Image

stored = False

try:
    info = open("info.txt").read().split("-")
    username=info[0]
    password=info[1]
    serverid=info[2]
    print "Stored values found: using them.  Delete info.txt to remove these."
    stored = True
except:
    print "No stored values found.  Prompting."
    username = raw_input("Enter your Minecraft username: ").strip()
    password =  raw_input("Enter your password: ").strip()
    serverid = raw_input("Enter the hash for the server (found in URL): ").strip()

print "Please wait.  Loading"
login = mechanize.Browser()
login.open("http://minecraft.net/login.jsp")
login.select_form("input")
login["username"] = username
login["password"] = password
login.submit()
response1 = login.open("http://minecraft.net/play.jsp?server="+serverid).read().splitlines()
for x in response1:
    if 'param name="mppass"' in x:
        mppass = x[x.find('value=')+7:x.find('">')]
    elif 'param name="server"' in x:
        server = x[x.find('value=')+7:x.find('">')]
    elif 'param name="username"' in x:
        NAME = x[x.find('value=')+7:x.find('">')]
    elif 'param name="port"' in x:
        port = int(x[x.find('value=')+7:x.find('">')])

if not stored:
    store = raw_input("Would you like to store these values in plaintext? y/N")
    if store == "y":
        print "Storing"
        try:
            open("info.txt", "w").write(username+"-"+password+"-"+serverid)
        except:
            raw_input("No info.txt found.  You must create one before storing! Press return to continue")
    else:
        print "Not storing!"

class Player:
    def __init__(self,name,pid):
        self.name    = name
        self.x       = 0
        self.y       = 0
        self.z       = 0
        self.heading = 0
        self.pitch   = 0
        self.pid     = pid

    def pos(self,x,y,z):
        self.x = x
        self.y = y
        self.z = z

    def delta_pos(self,x,y,z):
        self.x += x
        self.y += y
        self.z += z

    def orient(self,heading,pitch):
        self.heading = heading
        self.pitch   = pitch

    def __repr__(self):
        return "[%s:%s] @ (%s,%s,%s)"%(self.name,self.pid,self.x,self.y,self.z)

class Action:
    def __init__(self,bot):
        self.bot = bot
    def do(self):
        pass

class SleepAction(Action):       ## Okay, a much better thing would be to have
    def __init__(self,bot=None): ## some sort of a cron thing, I know.
        Action.__init__(self,bot)
    def do(self):
        pass

class MoveAction(Action):
    def __init__(self,bot,x,y,z):
        Action.__init__(self,bot)
        self.x, self.y, self.z = x,y,z
    def do(self):
        self.bot.move(self.x,self.y,self.z)

class DestroyBlockAction(Action):
    def __init__(self,bot,x,y,z):
        Action.__init__(self,bot)
        self.x, self.y, self.z = x,y,z
    def do(self):
        self.bot.destroy(self.x,self.y,self.z)

class SetBlockAction(Action):
    def __init__(self,bot,type,x,y,z):
        Action.__init__(self,bot)
        self.x, self.y, self.z, self.type = x,y,z,type
    def do(self):
        self.bot.set(self.x,self.y,self.z,self.type)

class TriggerAction(Action):
    def __init__(self,bot,func,args=None):
        Action.__init__(self,bot)
        self.f    = func
        self.args = args
    def do(self):
        if self.args:
            self.f(self.args)
        else:
            self.f()

class MultiAction(Action):
    def __init__(self,bot,*actions):
        Action.__init__(self,bot)
        self.actions = list(actions)
    def do(self):
        for action in self.actions:
            action.do()

class SayAction(Action):
    def __init__(self,bot,msg):
        Action.__init__(self,bot)
        self.msg = msg
    def do(self):
        self.bot.sendMessage(msg)

class DrawBot:
    def __init__(self,bot):
        self.bot = bot
        self.valid_blocks = valid_blocks ## Loaded from config.py
        self.block_names  = block_names  ## Loaded from config.py

                        ######         012345678901234567890123456789012345678901234567890/50
        self.cmd_help   = {"cuboid"    :"cuboid <type> - draws a 3D shape of blocks <type>",
                           "drawline"  :"drawline <type> - draws a line between 2pts",
                           "reset"     :"reset - resets the bot",
                           "goaway"    :"goaway - gets the bot out of your way",
                           "abort"     :"abort - makes the bot stop everything",
                           "copy"      :"copy <filename> - copies an area to a file",
                           "paste"     :"paste <filename> - builds from file",
                           "backup"    :"backup <filename> - backs the map up to a file",
                           "restore"   :"restore <filename> - restores to a backup",
                           "sponge"    :"sponge - helps with water cleanup.",
                           "erase"     :"erase <type> - erases blocks of that type",
                           "say"       :"say <msg> - Makes the bot say something.",
                           "p1"        :"p1 - sets point 1 in lieu of mushroom.",
                           "p2"        :"p2 - sets point 2 in lieu of mushroom.",
                           ##"replace"   :"replace <old>,<new> - replaces with new tiles",
                           "drawimg"   :"drawimg <image> - draw a 2D image with blocks"
                           }

        self.onReset(silent=True)

    def onReset(self,silent=False):
        self.user       = None
        self.first_pos  = None
        self.second_pos = None
        self.block_type = None
        self.mode       = None
        if not silent:
            self.bot.sendMessage("Drawing commands reset.")
        self.last_move  = (0,0,0)
        self.blocks     = []
        self.filename   = None          ## Used by copy/paste
        self.restore_filename = None    ## Used by restore

    def canUseBot(self,user):
        ## The bot (pid: 255) is trying to use itself.
        if self.bot.players[255].name == user:
            return False

        user = user.lower()

        try:
            with open("users.txt", "r") as f:
                for line in f:
                    if line.strip('\n').lower() == user:
                        return True
            return False
        except:
            return True

    def onMessage(self,pid,line):
        if not ":" in line:
            return

        words = [ x.strip() for x in line.split(":") ]
        user  = words[0]

        ## This strips anything like a title from a person's name
        ## ie: (Builder) Inside, <Builder> Inside, [Dev] InsideInside
        user = re.sub("[<([].*?[])>][ ]*",'',user)

        msg   = words[1]

        print "User: [%s:%s], message: [%s]"%(user,pid,msg)

        if (255 in self.bot.players) and (user == self.bot.players[255].name):
            print "[Ignoring a message produced by the bot]"
            return
#####
##### ToDo: Cleanup this section!
#####
        if (msg.split(" ")[0].replace(CMD_PREFIX, '') in self.cmd_help) and not self.canUseBot(user):
            self.bot.sendMessage("I'm sorry, but you can't use this bot.",ignorable=True)
            return

        if not " " in msg:
            ## Check for no argument commands
            if msg == CMD_PREFIX + "reset":
                self.onReset()
            elif msg == CMD_PREFIX + "abort":
                self.onAbort()
            elif msg == CMD_PREFIX + "help":
                self.onHelp()
            elif msg == CMD_PREFIX + "goaway":
                self.onGoAway()
            elif msg == CMD_PREFIX + "sponge":
                self.onSponge(user)
            elif msg == CMD_PREFIX + "p1":
                self.onSetPoint(user,1)
            elif msg == CMD_PREFIX + "p2":
                self.onSetPoint(user,2)
            elif msg.replace(CMD_PREFIX,'') in self.cmd_help:
                self.onHelp(msg.replace(CMD_PREFIX,''))
        else:
            ## Check for commands that take an argument
            words  = [ x.strip() for x in msg.split(" ") ]
            cmd    = words[0]
            arg    = " ".join(words[1:])
            print "Command: [%s], Argument: [%s]"%(cmd,arg)
            if cmd == CMD_PREFIX + "drawline":
                self.onDrawLine(user,arg)
            elif cmd == CMD_PREFIX + "cuboid":
                self.onDrawCuboid(user,arg)
            elif cmd == CMD_PREFIX + "help":
                self.onHelp(arg)
            elif cmd == CMD_PREFIX + "copy":
                self.onCopy(user,arg)
            elif cmd == CMD_PREFIX + "paste":
                self.onPaste(user,arg)
            elif cmd == CMD_PREFIX + "backup":
                self.onBackup(user,arg)
            elif cmd == CMD_PREFIX + "restore":
                self.onRestore(user,arg)
            elif cmd == CMD_PREFIX + "erase":
                self.onErase(user,arg)
            elif cmd == CMD_PREFIX + "replace":
                self.onReplace(user,arg)
            elif cmd == CMD_PREFIX + "say":
                self.onSay(user,arg)
            elif cmd == CMD_PREFIX + "drawimg":
                self.onDrawImage(user,arg)

    def onSetPoint(self,user,point_num):
        if not self.mode:
            self.bot.sendMessage("Nothing to set a point for",ignorable=True)
            return

        if not self.user == user:
            self.bot.sendMessage("Someone else is using the bot. Use %sreset to reset."%CMD_PREFIX)
            return

        pid = self.bot.hasPlayer(user)
        if pid == MinecraftBot.INVALID_PLAYER:
            self.bot.sendMessage("You are not in the map (somehow..)")
            return

        p = self.bot.players[pid]
        if point_num == 1:
            self.first_pos = ( int(p.x), int(p.y), int(p.z) )
            self.bot.sendMessage("Point 1 set.",ignorable=True)
        elif point_num == 2:
            self.second_pos = ( int(p.x) , int(p.y) , int(p.z) )
            self.bot.sendMessage("Point 2 set",ignorable=True)

        if self.first_pos and self.mode == "paste":
            self.Paste()
            self.onReset(silent=True)
            return
        elif self.first_pos and self.mode == "drawimg":
            self.DrawImage()
            self.onReset(silent=True)
            return

        if self.first_pos and self.second_pos:
            if self.mode == "line":
                self.DrawLine()
            elif self.mode == "cuboid":
                self.DrawCuboid()
            elif self.mode == "copy":
                self.Copy()
            elif self.mode == "restore":
                self.Restore()
            elif self.mode == "sponge":
                self.Sponge()
            elif self.mode == "erase":
                self.Erase()
            self.onReset(silent=True)

    def onSay(self,user,arg):
        self.bot.sendMessage(arg)

    def onBackup(self,user,filename):
        try:
            f = open(filename+".backup","r")
            self.bot.sendMessage("A backup by that name already exists.")
            f.close()
        except IOError:
            f = open(filename+".backup","wb")
            f.write(struct.pack("!3i",self.bot.level_x,self.bot.level_y,self.bot.level_z))
            self.bot.block_array.tofile(f)
            self.bot.sendMessage("Backup saved to file %s.backup"%filename)

    def onRestore(self,user,filename):
        try:
            f = open(filename+".backup")
            backup_header = f.read(12)
            x,y,z = struct.unpack('!3i',backup_header)
            if (not x == self.bot.level_x) or (not y == self.bot.level_y) or (not z == self.bot.level_z):
                self.bot.sendMessage("That backup is not for this map.")
                return
            self.user             = user
            self.mode             = "restore"
            self.restore_filename = filename
            self.bot.sendMessage("Place 2 brown shrooms to restore an area.",ignorable=True)
        except IOError:
            self.bot.sendMessage("No such backup exists.")

    def Restore(self):
        try:
            f = open(self.restore_filename+".backup","rb")
            header_x, header_y, header_z = struct.unpack('!3i',f.read(12))
            backup_array = array.array('B')
            backup_array.fromfile(f,header_x*header_y*header_z)
            x1,y1,z1 = self.first_pos
            x2,y2,z2 = self.second_pos
            if x1 > x2 : x1, x2 = x2, x1
            if y1 > y2 : y1, y2 = y2, y1
            if z1 > z2 : z1, z2 = z2, z1

            tiles_to_deglass = []
            tiles_to_build   = []
            while x1 <= x2:
                y = y1
                while y <= y2:
                    z = z1
                    while z <= z2:
                        offset = self.bot.calculateOffset(x1,y,z)
                        current_tile = int(self.bot.block_array[offset])
                        backup_tile  = int(backup_array[offset])
                        if not ( current_tile == backup_tile):
                            if (current_tile == 0) and (backup_tile in self.valid_blocks):
                                tiles_to_build.append((backup_tile,x1,y,z))
                            elif (current_tile >= 8) and (current_tile <= 11) and (backup_tile == 0):
                                ## This deals with water & lava in what used to be empty spaces
                                ## first we'll glass it all, and then deglass later!
                                self.blocks.append((20,x1,y,z))
                                tiles_to_deglass.append((0,x1,y,z))
                            elif backup_tile in self.valid_blocks:
                                ## This is the fall through... We'll try to erase
                                ## the current tile and then restore it to the other state
                                tiles_to_build.append((0,x1,y,z))
                                tiles_to_build.append((backup_tile,x1,y,z))
                            elif (backup_tile == 0) and not (current_tile == 0):
                                tiles_to_build.append((0,x1,y,z))

                        z+=1
                    y += 1
                x1 +=1
            self.DrawBlocks()
            self.blocks += tiles_to_build
            self.DrawBlocks()
            self.blocks += tiles_to_deglass
            self.DrawBlocks()
            self.bot.sendMessage("Done restoring.",ignorable=True)
            ##self.bot.action_queue.append(SayAction(self.bot,"Done restoring."))
            self.onReset(silent=True)

        except IOError:
            self.bot.sendMessage("Error while restoring (couldn't read file).")

    def onCopy(self,user,filename):
        if self.user:
            self.bot.sendMessage("%s is using the bot. Use %sreset to reset"%(self.user,CMD_PREFIX))
            return
        try:
            f = open(filename+".chunk")
            self.bot.sendMessage("A chunk by that name already exists.")
            f.close()
        except IOError:
            self.filename = filename
            self.user     = user
            self.mode     = "copy"
            self.bot.sendMessage("Place 2 shrooms to copy the cuboid",ignorable=True)

    def onSponge(self,user):
        if self.user:
            self.bot.sendMessage("%s is using the bot. Use %sreset to reset."%(self.user,CMD_PREFIX))
            return

        self.user     = user
        self.mode     = "sponge"
        self.bot.sendMessage("Define volume to deflood w/ 2 brown shrooms",ignorable=True)

    def Sponge(self):
        x1,y1,z1 = self.first_pos
        x2,y2,z2 = self.second_pos
        if x1 > x2: x1,x2 = x2,x1
        if y1 > y2: y1,y2 = y2,y1
        if z1 > z2: z1,z2 = z2,z1
        while x1 <= x2:
            y = y1
            while y <= y2:
                z = z1
                while z <= z2:
                    self.blocks.append( (19,x1,y,z) )
                    z+=5
                y+=5
            x1 +=5
        self.DrawBlocks()
        self.onReset(silent=True)

    def Copy(self,postfix=".chunk"):
        try:
            with open(self.filename + postfix,"wb") as f:
                x1,y1,z1 = self.first_pos
                x2,y2,z2 = self.second_pos
                if x1 > x2:
                    x1, x2 = x2, x1
                if y1 > y2:
                    y1, y2 = y2, y1
                if z1 > z2:
                    z1, z2 = z2, z1
                b = self.blocks
                ## +1 to the coordinate since the volume copied is inclusive of point 2
                f.write( struct.pack('!3i',x2 - x1+1, y2 - y1+1, z2 - z1+1) )
                while x1 <= x2:
                    y = y1
                    while y <= y2:
                        z = z1
                        while z <= z2:
                            offset = self.bot.calculateOffset(x1,y,z)
                            f.write( struct.pack('!B',int(self.bot.block_array[offset])))
                            z +=1
                        y +=1
                    x1 += 1

                self.bot.sendMessage("Copied volume to file %s"%self.filename)

        except IOError:
            self.bot.sendMessage("Couldn't write to file")
        finally:
            self.onReset(silent=True)

    def onPaste(self,user,arg):
        if self.user:
            self.bot.sendMessage("%s is using the bot. Use %sreset to reset."%(self.user,CMD_PREFIX))
            return

        try:
            f = open(arg + ".chunk","rb") ## just testing if the file exists
            f.close()
            self.bot.sendMessage("Place one brown mushroom to start pasting.",ignorable=True)
            self.user     = user
            self.filename = arg
            self.mode     = "paste"
        except IOError:
            self.bot.sendMessage("No such file [%s]"%arg)

    def Paste(self):
        try:
            with open(self.filename + ".chunk","rb") as f:
                ## I don't really know if x=width, y=depth, h=height
                ## I doubt that it's relevant
                w,d,h    = struct.unpack('!3i',f.read(12))
                x1,y1,z1 = self.first_pos
                x2,y2,z2 = x1+w, y1+d, z1+h

                while x1 < x2:
                    y = y1
                    while y < y2:
                        z = z1
                        while z < z2:
                            block_type = struct.unpack('!B', f.read(1))[0]
                            if block_type in self.valid_blocks:
                                self.blocks.append( (block_type,x1,y,z) )
                            elif block_type == 2:
                                self.blocks.append( (3,x1,y,z))
                            z+=1
                        y+=1
                    x1 += 1
            self.DrawBlocks()
            self.bot.sendMessage("Pasting file!",ignorable=True)
        except IOError:
            self.bot.sendMessage("Couldn't read from file")
        finally:
            self.onReset(silent=True)

    def onGoAway(self):
        self.bot.sendMessage(":(")
        self.bot.action_queue.append( MoveAction(self.bot,-1,-1,-1))

    def onHelp(self,arg=None):
        ### Todo: clean up this function so that it takes a list of commands
        ### built into the bot and then composes a string listing them
        ### instead of using a hard-coded string.
        if not arg:
            cmds = str( self.cmd_help.keys() ).replace(",","").replace("[","").replace("]","").replace("'","")
            self.bot.sendMessage("Cmds: %s"%cmds)
        elif arg in self.cmd_help:
            self.bot.sendMessage(self.cmd_help[arg])

    def onAbort(self):
        self.onReset(silent=True)
        self.bot.sendMessage("Flushed action queue.")
        self.bot.action_queue = []

    class BlockTypeError(Exception):
        def __init__(self,block_type):
            self.block_type = block_type
        def __str__(self):
            return "%s is not a valid block type."%self.block_type

    def getBlockType(self,arg):
        try:
            if arg.lower() in self.block_names: ## check string first, then try
                return self.block_names[arg]    ## conversion which may throw
            elif int(arg) in self.valid_blocks:
                return int(arg)
            else:
                raise DrawBot.BlockTypeError(arg)
        except:
            raise DrawBot.BlockTypeError(arg)

    def onDrawLine(self,user,arg):

        try:
            block_type = self.getBlockType(arg)
        except DrawBot.BlockTypeError as e:
            self.bot.sendMessage(str(e))
            return

        if self.user:
            self.bot.sendMessage("%s is using the bot. Use %sreset to reset."%(self.user,CMD_PREFIX))
            return

        self.bot.sendMessage("%s, place 2 brown shrooms to define a line."%user,ignorable=True)
        self.block_type = block_type
        self.user     = user
        self.mode = "line"

    def onErase(self,user,arg):
        try:
            block_type = self.getBlockType(arg)
        except DrawBot.BlockTypeError as e:
            self.bot.sendMessage(str(e))
            return

        if self.user:
            self.bot.sendMessage("%s is using the bot. Use %sreset to reset"%(self.user,CMD_PREFIX))
            return

        self.bot.sendMessage("%s, place 2 brown mushrooms to define a cuboid"%user,ignorable=True)
        self.block_type = block_type
        self.user = user
        self.mode = "erase"

    def onReplace(self,user,arg):
        pass

    def onDrawCuboid(self,user,arg):
        try:
            block_type = self.getBlockType(arg)
        except DrawBot.BlockTypeError as e:
            self.bot.sendMessage(str(e))
            return

        if self.user:
            self.bot.sendMessage("%s is using the bot. Use %sreset to reset."%(self.user,CMD_PREFIX))
            return

        self.bot.sendMessage("%s, place 2 brown mushroom to define a cuboid."%user,ignorable=True)
        self.block_type = block_type
        self.user = user
        self.mode = "cuboid"

    def onSetBlock(self,type,x,y,z):
        if (not type == 39) or (not self.user):
            return

        print self.bot.players

        pid = self.bot.hasPlayer(self.user)
        if not pid == MinecraftBot.INVALID_PLAYER:
            player = self.bot.players[pid]
            if self.bot.dist3d(player.x,player.y,player.z,x,y,z) < 10:
                if not self.first_pos:
                    self.first_pos = (x,y,z)

                    if self.mode == "paste":
                        self.Paste()
                else:
                    self.second_pos = (x,y,z)

                    if self.mode == "line":
                        self.DrawLine()
                    elif self.mode == "cuboid":
                        self.DrawCuboid()
                    elif self.mode == "copy":
                        self.Copy()
                    elif self.mode == "restore":
                        self.Restore()
                    elif self.mode == "sponge":
                        self.Sponge()
                    elif self.mode == "erase":
                        self.Erase()
                    elif self.mode == "drawimg":
                        self.DrawImage()
                    self.onReset(silent=True)
        else:
            self.onReset(silent=True)

    def Erase(self):
        self.bot.sendMessage("Erasing blocks of that type from the area",ignorable=True)
        x1,y1,z1 = self.first_pos
        x2,y2,z2 = self.second_pos
        if x1 > x2: x1,x2 = x2,x1
        if y1 > y2: y1,y2 = y2,y1
        if z1 > z2: z1,z2 = z2,z1

        while x1 <= x2:
            y = y1
            while y <= y2:
                z = z1
                while z <= z2:
                    offset = self.bot.calculateOffset(x1,y,z)
                    current_tile = int(self.bot.block_array[offset])
                    if current_tile == self.block_type:
                        self.blocks.append( (0,x1,y,z))
                    z+=1
                y+=1
            x1 += 1
        self.DrawBlocks()

    def DrawCuboid(self):
        self.bot.sendMessage("Drawing cuboid.",ignorable=True)
        x1,y1,z1 = self.first_pos
        x2,y2,z2 = self.second_pos

        if x1 > x2:
            x1,x2 = x2,x1
        if y1 > y2:
            y1,y2 = y2,y1
        if z1 > z2:
            z1,z2 = z2,z1

        if self.block_type == 0: ## We want to erase from the top down.
            while y2 >= y1:
                x = x1
                while x <= x2:
                    z = z1
                    while z <= z2:
                        self.blocks.append( (self.block_type,x,y2,z))
                        z += 1
                    x +=1
                y2 -=1
        else:
            while x1 <= x2:
                y = y1
                while y <= y2:
                    z = z1
                    while z <= z2:
                        self.blocks.append( (self.block_type, x1,y,z) )
                        z +=1
                    y+=1
                x1+=1
        self.DrawBlocks()

    def distSquared(self,x1,y1,z1,x2,y2,z2):
        return (x2-x1)**2 + (y2-y1)**2 + (z2-z1)**2

    def DrawBlocks(self ):
        build_loc = (0,0,0)

        blocks_to_build = []
        while len(self.blocks):
            block = self.blocks.pop(0)

            try:
                offset = self.bot.calculateOffset(*block[1:])
                current_tile = int(self.bot.block_array[offset])
            except IndexError as e:
                ## Out of bounds error
                continue

            ## No point in overwriting something if it's already there.
            if (current_tile == block[0]):
                continue

            ## deleting water/lava/air is useless
            if ( block[0] == 0) and (((current_tile >= 8) and (current_tile <= 11)) or (current_tile == 0)):
                continue

            ## The server complains if you build too many bricks at the same time.
            if (self.distSquared(*(build_loc + block[1:])) < 25) and len(blocks_to_build) < 5:
                blocks_to_build.append(block)
            else:
                ma = MultiAction(self.bot)
                for b in blocks_to_build:
                    if b[0] == 0:
                        ma.actions.append( DestroyBlockAction(self.bot,*b[1:]))
                    else:
                        ma.actions.append( SetBlockAction(self.bot,*b))
                blocks_to_build = []

                build_loc = block[1:]
                ma.actions.append(MoveAction(self.bot,*build_loc))
                self.bot.action_queue.append( ma )
                self.bot.action_queue.append( SleepAction() )
                ## Ipha's code suggests that you should send moveaction twice..
                self.bot.action_queue.append( MoveAction(self.bot, *build_loc) )
                blocks_to_build.append(block)

        ma = MultiAction(self.bot)
        for b in blocks_to_build:
            if b[0] == 0:
                ma.actions.append( DestroyBlockAction(self.bot,*b[1:]))
            else:
                ma.actions.append( SetBlockAction(self.bot,*b))
        self.bot.action_queue.append(ma)

    def DrawLine(self):
        self.bot.sendMessage("Drawing line.",ignorable=True)
        fp = self.first_pos
        sp = self.second_pos
        ## This is the vector from pt 1 to pt 2
        x,y,z = sp[0] - fp[0], sp[1] - fp[1], sp[2] - fp[2]

        ## magnitude of that vector
        dist = self.bot.dist3d(fp[0], fp[1], fp[2], sp[0], sp[1], sp[2] )

        ## unit vector
        n_x, n_y, n_z = x/dist, y/dist, z/dist

        ## stepping a dist of 1 in the direction of the unit vector, find the
        ## whole coordinate and place a block at that location
        coords = []
        for d in xrange(0, int(dist)):
            self.blocks.append( (
                           self.block_type,
                           int(round(fp[0] + (n_x * d))),
                           int(round(fp[1] + (n_y * d))),
                           int(round(fp[2] + (n_z * d)))
                           ) )
        self.DrawBlocks()

    def onStart(self):
        pass

    def onDrawImage(self,user,arg):
        try:
            img = Image.open(arg)
        except IOError as e:
            self.bot.sendMessage(str(e))
            return

        if self.user:
            self.bot.sendMessage("%s is using the bot. Use %sreset to reset."%(self.user,CMD_PREFIX))
            return

        self.bot.sendMessage("%s, place one shroom to start drawing."%user,ignorable=True)
        self.img = img
        self.user = user
        self.mode = "drawimg"

    def DrawImage(self):
        try:
            self.img = self.img.convert('RGBA')
            self.img = self.img.resize((self.img.size[0] * 0.125, self.img.size[1] * 0.125), Image.NEAREST)
            pixels = self.img.load()
            x1,y1,z1 = self.first_pos
            
            for x in xrange(0,self.img.size[0]):
                for y in xrange(0,self.img.size[1]):
                    p = pixels[x,y]
                    if p[3] != 0: # not transparent
                        block = self.selectBlockByRGB(p)
                        self.blocks.append((block, x1 - x + self.img.size[0], y1 - y + self.img.size[1], z1))
            
            self.DrawBlocks()
            self.bot.sendMessage("Drawing image.",ignorable=True)
        except Exception as e:
            self.bot.sendMessage("Error drawing image: %s" % str(e))
        finally:
            self.onReset(silent=True)
            
    def selectBlockByRGB(self,pixel):
        distance = sys.maxint
        selected_block = None
        for block, rgb in block_colors.iteritems():
            r = (pixel[0] - rgb[0]) ** 2
            g = (pixel[1] - rgb[1]) ** 2
            b = (pixel[2] - rgb[2]) ** 2
            temp = (r ** .5) + (g ** .5) + (b ** .5)
            if temp == 0:
                return block
            elif temp < distance:
                distance = temp
                selected_block = block
        return selected_block

class MinecraftBot:
    INVALID_PLAYER = -1
    def __init__(self):
        self.reset()

    def reset(self):
        self.level_data   = ""
        self.players      = {}
        self.info         = None
        self.action_queue = []
        self.bot          = DrawBot(self)
                             ## For the cylinder that was bore down, argument was (180,125,96,17)
                             ## cylinder along x axis -- (255,50,96,17)
                             ## cylinder along z-axis -- (180,50,255,17)
        self.block_array  = None
        self.level_x      = None
        self.level_y      = None
        self.level_z      = None

        self.loading_map    = True
        self.building_queue = [] ## This is used for storing setblocks() which are sent
                                 ## while the map is not fully loaded (ie: on multi-world servers)


    def hasPlayer(self,name):
        for k,v in self.players.iteritems():
            if v.name == name:
                return k
        return MinecraftBot.INVALID_PLAYER

    def onServerJoin(self, version, srv_name, motd, user_type):
        self.loading_map = True
        self.reset()
        print "Joined server! Ver: %s, Name: %s, Motd: %s, Your type: %s"%(version,srv_name,motd,user_type)

    def onPing(self): ## atm does nothing?
        pass

    def onLevelStart(self): ## no actual data sent along with this
        print "Receiving level data"

    def onLevelData(self,length,data,percent_complete): ##
        self.level_data += data
        print "Downloading level, %s complete."%percent_complete

    def onLevelEnd(self,x,y,z): ## size of the level (x,y,z)
        print "Level downloaded. Size: (%s,%s,%s)"%(x,y,z)
        f_name = "out.gz"

        ## Striping tailing zeroes from the level data as the data transmitted
        ## has a length equal to a multiple of 1024 bytes, padded with trailing
        ## zeroes.
        self.level_data = self.level_data.strip('\x00')

        ## Below is a hack to get around the fact that Python 2.6 can't handle
        ## gzipped files that have been zero padded. More here:
        ## http://bugs.python.org/issue2846
        fail_counter = 0
        data = ""
        while fail_counter < 4:
            try:
                sio  = StringIO(self.level_data)
                gzf  = GzipFile(fileobj = sio, mode="rb+")
                num_blocks = struct.unpack('!l',gzf.read(4))
                data = gzf.read()
                break
            except:
                print "Failed to read gzip file.. [Attempt %s]"%fail_counter
                fail_counter += 1
                self.level_data += "\x00"

        print "Writing %s bytes to %s"%(len(self.level_data),f_name)
        with open(f_name, "wb") as f:
            f.write(self.level_data)

        with open("level.data","wb") as f:
            f.write(data)

        ##self.block_array = numpy.frombuffer(data, dtype="uint8")
        self.block_array = array.array('B')
        self.block_array.fromstring(data)
        print "Number of blocks received in file: %s"%num_blocks
        print "Number of elements in the array :%s"%len(self.block_array)
        self.level_data = ""
        self.level_x = z
        self.level_y = y
        self.level_z = x
        self.loading_map = False
        print "Level data written to file!"

        for b in self.building_queue:
            self.onSetBlock( *b )


    def dist3d(self,x1,y1,z1,x2,y2,z2):
        return math.sqrt( (x2-x1)**2 + (y2-y1)**2 + (z2-z1)**2)

    def calculateOffset(self,x,y,z):
        ## Okay, I don't know why, but.... x is z and z is x.
        ## yes, weird, I know.
        if ((x < 0) or (z > self.level_x) or
            (y < 0) or (y > self.level_y) or
            (z < 0) or (x > self.level_z)):
                raise IndexError(" (%s,%s,%s) is out of bounds"%(x,y,z))

        return y*(self.level_x * self.level_z) + z*self.level_z + x

    def onSetBlock(self,type,x,y,z):
        if (not self.block_array) or (self.loading_map):
            print "Saved block for later building."
            self.building_queue.append( (type,x,y,z) )
            return

        self.bot.onSetBlock(type,x,y,z)
        try:
            offset = self.calculateOffset(x,y,z)
        except:
            print "Received out of bounds setBlock (changing maps?)"
            self.building_queue.append( (type,x,y,z))
            return

        ## I'm assuming that the server is just sending new block data ahead of time
        ## and will actually send more blocks in the future.
        if offset > len(self.block_array) - 1:
            print "Saved block for later building"
            self.building_queue.append( (type,x,y,z))
        else:
            self.block_array[ offset ] = type

    def onSpawnPlayer(self,pid,name,x,y,z,heading,pitch):
        name = re.sub('&.','',name) ## strip color codes, if any
        p = Player(name,pid)
        p.pos(x,y,z)
        p.orient(heading,pitch)
        self.players[pid] = p

        if pid == 255: ## that is, the bot's info has been sent.
            self.info = p
            self.start_bot() ## Coincidentally, this is when we start the bot!

        print "Spawned player %s [PID:%s]"%(name,pid)

    def onPlayerUpdate(self,pid,x,y,z,heading,pitch):
        if pid in self.players:
            p = self.players[pid]
            p.pos(x,y,z)
            p.orient(heading,pitch)

    def onPlayerUpdate2(self,pid,x,y,z,heading,pitch):
        pass ## As I'm not sure what to do with the data

    def onPositionUpdate(self,pid,delta_x,delta_y,delta_z):
        if pid in self.players:
            p = self.players[pid]
            p.delta_pos(delta_x,delta_y,delta_z)

    def onOrientationUpdate(self,pid,heading,pitch):
        if pid in self.players:
            p = self.players[pid]
            p.orient(heading,pitch)

    def onDespawnPlayer(self,pid):
        if pid in self.players:
            name = self.players[pid].name
            print "Removed player %s"%name
            del self.players[pid]
        else:
            print "Removed unknown player with pid %s"%pid

    def onMessage(self,pid,message):
        message = re.sub('&.','',message) ## strip color codes, if any
        print "<%s>"%(message)
        self.bot.onMessage(pid,message)

    def onKick(self,message):
        print "Got kicked! Reason: %s"%message

    def onChangeUserType(self,new_type):
        pass

    def start_bot(self):
        ## Here we'll start our bot thingamugummy
        self.bot.onStart()

        ## This handles the periodic updates to the server
        update = task.LoopingCall(self.update_server)
        update.start(.1)

        ## This sends out one action every 1/10th of a second
        action = task.LoopingCall(self.do_action)
        action.start(BUILD_SPEED)

    def update_server(self):
        ## start_bot() is called right when the level is done loading
        ## but for a brief second, the client's pid/position is not yet sent.
        if not self.info: ## for a while we won't get information about our avatar.
            return
        p = self.info
        self.protocol.sendPosition(p.x,p.y,p.z,p.heading,p.pitch)

    def do_action(self):
        if self.action_queue and self.info:
            i = self.action_queue.pop(0)
            i.do()

    def move(self,x,y,z):
        self.info.x = x
        self.info.y = y
        self.info.z = z

    def destroy(self,x,y,z):
        self.protocol.setBlock(0x00,0x01,x,y,z,)
                         ##    ^     ^- Stone Block Type
                         ##    |------- 0x00 is destroy signal

    def set(self,x,y,z,type):
        self.protocol.setBlock(0x01,type,x,y,z)
                         ##     ^- 0x01 is set block

    def sendMessage(self,msg,ignorable=False):
        if not (SILENT_MODE and ignorable) and not ABSOLUTE_SILENT_MODE:
            self.protocol.sendMessage(msg)

class MinecraftBotProtocol(Protocol):
    def __init__(self,bot):
        self.bot = bot
        self.buffer = ''
        self.level_buffer = ''
        self.packet_length = {'\x00': 131,  ## server id
                            '\x01': 1,    ## ping
                            '\x02': 1,    ## level initialize
                            '\x03': 1028, ## level data
                            '\x04': 7,    ## level loaded
                            '\x06': 8,    ## set block
                            '\x07': 74,   ## spawn player
                            '\x08': 10,   ## player update
                            '\x09': 7,    ## player update?
                            '\x0a': 5,    ## position update?
                            '\x0b': 4,    ## orientation update
                            '\x0c': 2,    ## despawn player
                            '\x0d': 66,   ## text message
                            '\x0e': 65,   ## kick message
                            '\x0f': 2     ## usermode changed
                            }
        self.packet_name = {'\x00': 'server id',
                            '\x01': 'ping',
                            '\x02': 'level initialize',
                            '\x03': 'level data',
                            '\x04': 'level loaded',
                            '\x06': 'set block',
                            '\x07': 'spawn player',
                            '\x08': 'player update',
                            '\x09': 'player update?',
                            '\x0a': 'position update?',
                            '\x0b': 'orientation update?',
                            '\x0c': 'despawn player',
                            '\x0d': 'text message',
                            '\x0e': 'kick message',
                            '\x0f': 'usermode changed'
                            }
    def sendMessage(self,msg):
        type = 0x0d
        pad   = 0 ## there's an unused pad byte for this packet
        while not len(msg) == 0:
            max_msg_len = 64 - 12 - 2 ## Magic number :/
            chunk  = msg[0:max_msg_len].ljust(64)
            msg    = msg[len(chunk):]
            packet = struct.pack('!BB64s',type,pad,chunk)
            self.transport.write(packet)

    def setBlock(self,mode,block_type,x,y,z):
        ##print "%s %s %s %s %s"%(mode,block_type,x,y,z)
        type   = 0x05
        x      = int(x)
        y      = int(y)
        z      = int(z)
        packet = struct.pack('!BhhhBB',type,x,y,z,mode,block_type)
        self.transport.write(packet)

    def sendPosition(self,x,y,z,heading=0,pitch=0):
        type = 0x08 ## position update packet type
        pid  = 255  ## the player id is always 255 when sending updates
        x = int(x*32)
        y = int(y*32)
        z = int(z*32)
        heading = heading * 256/360
        pitch   = pitch   * 256/360
        packet = struct.pack('!BBhhhBB',type,pid,x,y,z,heading,pitch)
        self.transport.write(packet)

    def dataReceived(self, data):
        self.buffer += data
        packet_type = self.buffer[0]

        while (len(self.buffer)) and (len(self.buffer) >= self.packet_length[packet_type]):
            self.process_data()
            if self.buffer:
                packet_type = self.buffer[0]

    def process_data(self):
        packet_type = self.buffer[0]
        length = self.packet_length[packet_type]
        if len(self.buffer) >= length:
            ##print ('Packet type: %s, Length: %s'%(self.packet_name[packet_type],length))
            data = self.buffer[:length]
            self.dispatch_events(data)
            self.buffer = self.buffer[length:] ## trim this much data
        else:
            print ('Incomplete Packet [1]')

    def dispatch_events(self,data):
        packet_type = data[0]
        data = data[1:]
        if packet_type == '\x00':
            d = struct.unpack('B64s64sB',data)
            version     = d[0]
            srv_name    = d[1].strip()
            motd        = d[2].strip()
            usertype    = d[3]
            self.bot.onServerJoin(version,srv_name,motd,usertype)
        elif packet_type == '\x01':
            self.bot.onPing()
        elif packet_type == '\x02':
            self.bot.onLevelStart()
        elif packet_type == '\x03':
            d = struct.unpack('!h1024sB',data)
            length       = d[0]
            level_data   = d[1]

            print "Level chunk length: %s"%length
            level_data   = d[1][:length]

            completeness = d[2]
            self.bot.onLevelData(length,level_data,completeness)
        elif packet_type == '\x04':
            d = struct.unpack('!hhh',data)
            self.bot.onLevelEnd(*d)
        elif packet_type == '\x06':
            d    = struct.unpack('!hhhB',data)
            x    = d[0]
            y    = d[1]
            z    = d[2]
            type = d[3]
            self.bot.onSetBlock(type,x,y,z)
        elif packet_type == '\x07':
            d = struct.unpack('!B64s3h2B',data)
            pid     = d[0]
            name    = d[1].strip()
            x       = d[2]/32.0
            y       = d[3]/32.0
            z       = d[4]/32.0
            heading = d[5]*360/256
            pitch   = d[6]*360/256
            self.bot.onSpawnPlayer(pid,name,x,y,z,heading,pitch)
        elif packet_type == '\x08':
            d = struct.unpack('!BhhhBB',data)
            pid     = d[0]
            x       = d[1]/32.0
            y       = d[2]/32.0
            z       = d[3]/32.0
            heading = d[4]*360/256
            pitch   = d[5]*360/256
            self.bot.onPlayerUpdate(pid,x,y,z,heading,pitch)
        elif packet_type == '\x09':
            d = struct.unpack('BbbbBB',data)
            pid     = d[0]
            x       = d[1]/32.0
            y       = d[2]/32.0
            z       = d[3]/32.0
            heading = d[4]*360/256
            pitch   = d[5]*360/256
            self.bot.onPlayerUpdate2(pid,x,y,z,heading,pitch)
        elif packet_type == '\x0a':
            d = struct.unpack('Bbbb',data)
            pid = d[0]
            d_x = d[1]/32.0
            d_y = d[2]/32.0
            d_z = d[3]/32.0
            self.bot.onPositionUpdate(pid,d_x,d_y,d_z)
        elif packet_type == '\x0b':
            d = struct.unpack('BBB',data)
            pid     = d[0]
            heading = d[1]*360/256
            pitch   = d[2]*360/256
            self.bot.onOrientationUpdate(pid,heading,pitch)
        elif packet_type == '\x0c':
            d = struct.unpack('B',data)
            self.bot.onDespawnPlayer(*d)
        elif packet_type == '\x0d':
            d = struct.unpack('B64s',data)
            pid = d[0]
            msg = d[1].strip()
            self.bot.onMessage(pid,msg)
        elif packet_type == '\x0e':
            d = struct.unpack('64s',data)
            kick_msg = d[0].strip()
            self.bot.onKick(kick_msg)
        elif packet_type == '\x0f':
            d = struct.unpack('B',data)
            self.bot.onChangeUserType(*d)
        else:
            print "Protocol error"
            reactor.stop()

    def connectionMade(self):
            print("Sending connection string")
            player_id = ''
            player_id += struct.pack('b', 0x00) ## packet type
            player_id += struct.pack('b', 0x07) ## protocol version
            player_id += NAME.ljust(64,' ')     ## name
            player_id += mppass.ljust(64, ' ')  ## verification string
            player_id += struct.pack('b', 0x00) ## unused
            self.transport.write(player_id)

class MinecraftBotClientFactory(ClientFactory):
    def __init__(self):
        self.bot = MinecraftBot()

    def startedConnecting(self, connector):
        print 'Started to connect.'

    def buildProtocol(self, addr):
        print 'Connected.'
        protocol = MinecraftBotProtocol(self.bot)
        self.bot.protocol = protocol
        return protocol

    def clientConnectionLost(self, connector, reason):
        print 'Lost connection.  Reason:', reason
        reactor.stop()

    def clientConnectionFailed(self, connector, reason):
        print 'Connection failed. Reason:', reason
        reactor.stop()

print "Running bot"

try:
    reactor.connectTCP(server,port,MinecraftBotClientFactory())
    reactor.run()
except:
    print "Couldn't retrieve information about the server from minecraft.net"
    print "This means that either: a) The server is down "
    print "                     or b) The hash is incorrect."
    print "http://minecraft.net/play.jsp?server=72d0bc9151c52126c8f45171b0e2f107"
    print "                                     <  this part here is the hash  > "