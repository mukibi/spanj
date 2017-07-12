#!/usr/bin/perl

use strict;
use warnings;
use DBI;
use Fcntl qw/:flock SEEK_END/;
require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d);
my %session;
my $authd = 0;
my $logd_in = 0;
my $id;
my $full_user = 0;
my @privs;

if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;
	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}
	#logged in 
	if (exists $session{"id"}) {
		$logd_in++;
		$id = $session{"id"};
		#privileges set
		if (exists $session{"privileges"}) {
			my $priv_str = $session{"privileges"};
			my $spc = " ";
			$priv_str =~ s/\+/$spc/g;
			$priv_str =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			if ($priv_str eq "all") { 
				$full_user++;
				$authd++;
			}
			else {
				if (exists $session{"token_expiry"} and $session{"token_expiry"} =~ /^\d+$/) {
					if ($session{"token_expiry"} > time) {
						@privs = split/,/,$priv_str;	
						foreach (@privs) {	
							if ($_ =~ /^CSR\(\*\)$/i) {
								$authd++;
								last;
							}
						}
					}
				}
			}
		}
	}
}

my %auth_params;
my $valid_data_posted = 0;
if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	$valid_data_posted = 1;
	my $str = "";

	while (<STDIN>) {
               	$str .= $_;
       	}

	my $space = " ";
	$str =~ s/\x2B/$space/ge;

	my @auth_req = split/&/,$str;
	for my $auth_req_line (@auth_req) {
		my $eqs = index($auth_req_line, "=");	
		if ($eqs > 0) {
			my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1)); 
			$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$auth_params{$k} = $v;
		}
	}
}
my @errors = ();
my $feedback = '';

my $study_years = 0;
my ($year_err, $class_err, $size_err) = ("", "", "");
my ($grad_year, $start_year, $class, $size);
my $con;

#check posted data for validity
if  ($valid_data_posted) {
	if (exists $auth_params{"grad_year"}) {
		if ($auth_params{"grad_year"} =~ /^\d+$/) {
			$valid_data_posted++;
			$grad_year = $auth_params{"grad_year"};
		}
		else {
			push @errors, "Invalid graduating year specified.";
			$year_err = "*";		
		}
	}
	else {
		push @errors, "No graduating year specified.";
		$year_err = "*";
	}

	if (exists $auth_params{"class"}) {
		my $input_class = $auth_params{"class"};
		my $valid_classes = "";
		$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});	
		if ($con) {
			my $prep_stmt = $con->prepare("SELECT value FROM vars WHERE id='1-classes' LIMIT 1");
			if ($prep_stmt) {
				my $rc = $prep_stmt->execute();
				if ($rc) {
					$valid_classes = ($prep_stmt->fetchrow_array())[0];
				}
				else {
					print STDERR "Could not execute SELECT FROM vars: ", $prep_stmt->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM vars: ", $prep_stmt->errstr, $/;  
			}
		}
		else {
			print STDERR "Cannot connect: $con->strerr$/";
		}
		my @classes_list = split/,/, $valid_classes;
		my $valid_class = 0;	
		J: for my $clas (@classes_list) {
			if ($clas =~ /(\d+)/) {
				my $cur_yr = $1;
				if ($cur_yr > $study_years) {
					$study_years = $cur_yr;
				}
			}
			if (lc($clas) eq lc($input_class)) {
				$class = $clas;
				$valid_class++;
				$valid_data_posted++;	
			}
		}
		unless ($valid_class) {
			if (@classes_list) {
				push @errors, "The system is configured to recognize one of the following values as a valid class: " . join(', ', @classes_list) . ". To change this setting, ask your administrator to alter the 'classes' system variable.";
				$class_err = "*";
			}
			else {
				push @errors, "The 'classes' system variable is not set. To proceed, ask your administrator to set this variable.";
				$class_err = "*";
			}
		}
	}
	else {
		push @errors, "No class specified.";
		$class_err = "*";
	}

	if (exists $auth_params{"size"}) {
		if ($auth_params{"size"} =~ /^\d+$/) {
			$size = $auth_params{"size"};
			$valid_data_posted++;
		}
		else {
			push @errors, "Invalid size specified.";
			$size_err = "*";
		}
	}
	else {
		push @errors, "No size specified.";
		$size_err = "*";
	}
	if (exists $auth_params{"confirm_code"}) {
		if ($auth_params{"confirm_code"} eq $session{"confirm_code"}) {
			$valid_data_posted++;
		}
		else {
			push @errors, "Invalid authorization code received. Do not alter the hidden values in the HTTP form.";
		}
	}
	else {
		push @errors, "No authorization code received with this request. Reload this page to receive a token.";
	}
	unless ($valid_data_posted >= 5) {
		$valid_data_posted = 0;
		if (@errors) {
			my $err_str = '';
			foreach (@errors) {
				$err_str .= "<li>" . $_;
			}
			$feedback = qq{<p><span style="color: red">Could not create roll due to the following issue(s):</span><br><ol>} . $err_str . "</ol>";
		}
		else {
			$feedback = qq{<p><span style="color: red">Could not create roll</span>};
		}
	}
	if ($study_years > 0) {
		$start_year = $grad_year - ($study_years - 1);
	}
}
 
my $content = '';

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a>&nbsp;--&gt;&nbsp;<a href="/cgi-bin/createroll.cgi">Create Student Roll</a>
	<hr> 
};

if ($authd) {
	if ($valid_data_posted) {
		unless ($con) {
			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});	
		}
		if ($con) {
			#check if this roll exists
			my $stream = $class;
			$stream =~ s/\d//g;
			my $collision = undef;
			my $prep_stmt = $con->prepare("SELECT table_name, class FROM student_rolls WHERE start_year=? and grad_year=?");
			if ($prep_stmt) {
				my $rc = $prep_stmt->execute($start_year, $grad_year);
				if ($rc) {
					while (my @rslts = $prep_stmt->fetchrow_array()) {
						my $rslts_class = $rslts[1];
						$rslts_class =~ s/\d//g;
						if (lc($rslts_class) eq lc($stream)) {
							$collision = $rslts[0];
						}
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM student_rolls: ", $prep_stmt->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM student_rolls: ", $prep_stmt->errstr, $/;  
			}

			#roll exists
			#offer edit this roll option
			if (defined $collision) {
				$content =
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Create Student Roll</title>
</head>
<body>
$header
<em>The student roll for $class (graduating class of $grad_year) already exists. Would you like to <a href="/">edit this student roll</a> instead?</em>
};

			}
	
			#add this roll to DB
			else { 
				#Avoid collisions on table name 
				my %possib_table_names = ();
				foreach (0..4) {
					$possib_table_names{gen_token(1)}++;
				}
			
				my @where_clause_bits = ();
				foreach (keys %possib_table_names) {
					push @where_clause_bits, "table_name=?";
				}
			
				my $where_clause = 'WHERE ' . join(' OR ', @where_clause_bits);

				my $prep_stmt2 = $con->prepare("SELECT table_name FROM student_rolls $where_clause");
				if ($prep_stmt2) {
					my $rc = $prep_stmt2->execute(keys %possib_table_names);
					if ($rc) {
						while (my @rslts = $prep_stmt2->fetchrow_array()) {
							delete $possib_table_names{$rslts[0]};	
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM student_rolls: ", $prep_stmt2->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM student_rolls: ", $prep_stmt2->errstr, $/;
				}
				my $t_name = time;
				if ( keys(%possib_table_names) ) {
					$t_name = (keys %possib_table_names)[0];
				}

				my $prep_stmt3 = $con->prepare("REPLACE INTO student_rolls VALUES (?,?,?,?,?)");
				if ($prep_stmt3) {
					my $rc = $prep_stmt3->execute($t_name, $class, $start_year, $grad_year, $size);
					#log create roll
					#add edit roll privelege for class
					unless ($rc) {
						print STDERR "Could not execute REPLACE INTO student_rolls: ", $prep_stmt3->errstr, $/;
					}
					unless ($full_user) {	
						my $prep_stmt4 = $con->prepare(qq{UPDATE tokens SET privileges=concat(privileges, ',ESR($class)') WHERE value=? LIMIT 1});
						
						if ($prep_stmt4) {
							my $rc = $prep_stmt4->execute($id);	
							unless ($rc) {
								print STDERR "Could not execute UPDATE tokens: ", $prep_stmt4->errstr, $/;	
							}
						}
						push @privs, "ESR($class)";
						$session{"privileges"} = join(',', @privs); 
					}
					my $prep_stmt5 = $con->prepare("CREATE TABLE `$t_name` (adm smallint unsigned unique, s_name varchar(16), o_names varchar(64), has_picture varchar(3), marks_at_adm smallint unsigned, subjects varchar(256), clubs_societies varchar(80), sports_games varchar(48), responsibilities varchar(48), house_dorm varchar(48))");
					if ($prep_stmt5) {
						my $rc = $prep_stmt5->execute();	
						unless ($rc) {
							print STDERR "Could not execute CREATE TABLE: ", $prep_stmt5->errstr, $/;	
						}
					}
					$con->commit();
				}
				else {
					print STDERR "Could not prepare REPLACE INTO student_rolls: ", $prep_stmt2->errstr, $/;
				}
				my @today = localtime;	
				my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
				open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
        			if ($log_f) {
                			@today = localtime;	
					my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
					flock ($log_f, LOCK_EX) or print STDERR "Could not log create student roll for $id due to flock error: $!$/"; 
					seek ($log_f, 0, SEEK_END);
		 			print $log_f "$id CREATE STUDENT ROLL ($class, Class of $grad_year) $time\n";
					flock ($log_f, LOCK_UN);
                			close $log_f;
        			}
				else {
					print STDERR "Could not log create student roll for $id: $!\n";
				}
#New student roll created
#appropriate privileges appended
				$content =
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Create Student Roll</title>
</head>
<body>
$header
<em>The student roll for $class (graduating class of $grad_year) has been created. Would you like to <a href="/cgi-bin/editroll.cgi?roll=$t_name">add names to it</a> now?</em>
};
			}
			$con->disconnect();
		}
		else {
			print STDERR "Cannot connect: $con->strerr$/";
		}
	}
	else {
		my $conf_code = gen_token();
		$session{"confirm_code"} = $conf_code;	
		$content =
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Create Student Roll</title>
</head>
<body>
$header
$feedback
<form autocomplete="off" action="/cgi-bin/createroll.cgi" method="POST">
<input type="hidden" name="confirm_code" value="$conf_code">
<table cellspacing="2%">
<tr>
<td><label for="grad_year"><span style="color: red">$year_err</span>Class of (Graduating year)</label>
<td><input type="text" name="grad_year" value="" size="15" maxlength="4">
<tr>
<td><label for="class"><span style="color: red">$class_err</span>Class/Stream (e.g. 8x or 3 Blue)</label>
<td><input type="text" name="class" size="15" value="">
<tr>
<td><label for="size"><span style="color: red">$size_err</span>Number of of students in class</label>
<td><input type="text" name="size" size="15" value="">
<tr>
<td><input type="submit" name="create" value="Create">
</table>
</form>
</body>
</html>
};
	}
}

else {
	if ($logd_in) {
		$content = 
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Create Student Roll</title>
</head>
<body>
$header
<em>Sorry. You are not authorized to create a student roll.<br><br>Get an up-to-date token with the appropriate privileges from the administrator.</em>
</body>
</html>	
};
	}
	#user not logged in, send them to
	#the login page
	else {
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /login.html?cont=/cgi-bin/createroll.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
               	"<html>
               	<head>
		<title>Spanj: Exam Management Information System - Redirect Failed</title>
		</head>
         	<body>
                You should have been redirected to <a href=\"/login.html?cont=/cgi-bin/createroll.cgi\">/login.html?cont=/cgi-bin/createroll.cgi</a>. If you were not, <a href=\"/cgi-bin/createroll.cgi\">Click Here</a> 
		</body>
                </html>";

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
	}
}

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=iso-8859-1\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

my @new_sess_array = ();

for my $sess_key (keys %session) {
	push @new_sess_array, $sess_key."=".$session{$sess_key};        
}
my $new_sess = join ('&',@new_sess_array);

print "X-Update-Session: $new_sess\r\n";

print "\r\n";
print $content;

sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}
